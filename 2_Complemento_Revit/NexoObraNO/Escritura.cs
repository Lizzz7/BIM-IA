// Registro del metrado diario. Desde la versión 0.2 los metrados ejecutados se guardan SOLO en el panel
// (archivo registros_<modelo>.json junto a los datos del cronograma), nunca en el modelo de Revit.
//  · "elementos": { "<ElementId>": { "registro": "aaaa-mm-dd|ítem|cantidad;...", "obs": "alertas de mayor metrado" } }
//  · "global": registro de las partidas sin elementos en el modelo (provisionales, excavación, ...)
// Cada escritura se hace en un archivo temporal y se reemplaza; además se guarda una copia diaria en «respaldos_registros».
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace NexoObraNO
{
    public class Registro1 { public long id { get; set; } public string item { get; set; } public double cantidad { get; set; } }
    public class PedidoMetrado { public string fecha { get; set; } public bool simular { get; set; } public List<Registro1> registros { get; set; } }

    public static class Escritura
    {
        static readonly CultureInfo CI = CultureInfo.InvariantCulture;
        static readonly object Candado = new object();

        public static string Ruta(Config cfg)
        {
            var b = Datos.Base(cfg);
            return Path.Combine(Path.GetDirectoryName(cfg.datos), $"registros_{(string)b["modelo"]}.json");
        }

        /// <summary>Lee el archivo de registros (vacío si aún no existe).</summary>
        public static JsonObject Leer(Config cfg)
        {
            lock (Candado)
            {
                var r = Ruta(cfg);
                if (!File.Exists(r)) return new JsonObject { ["elementos"] = new JsonObject(), ["global"] = "" };
                var o = JsonNode.Parse(File.ReadAllText(r)).AsObject();
                o["elementos"] ??= new JsonObject(); o["global"] ??= "";
                return o;
            }
        }

        static void Guardar(Config cfg, JsonObject o)
        {
            var r = Ruta(cfg);
            var tmp = r + ".tmp";
            File.WriteAllText(tmp, o.ToJsonString(new JsonSerializerOptions { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping }));
            if (File.Exists(r))
            {
                var dir = Path.Combine(Path.GetDirectoryName(r), "respaldos_registros");
                Directory.CreateDirectory(dir);
                var copia = Path.Combine(dir, Path.GetFileNameWithoutExtension(r) + "_" + DateTime.Now.ToString("yyyy-MM-dd") + ".json");
                if (!File.Exists(copia)) File.Copy(r, copia);          // primera versión de cada día
                File.Replace(tmp, r, null);
            }
            else File.Move(tmp, r);
        }

        public static Dictionary<string, double> Sumas(string reg)
        {
            var d = new Dictionary<string, double>();
            foreach (var x in (reg ?? "").Split(';', StringSplitOptions.RemoveEmptyEntries))
            {
                var p = x.Split('|');
                if (p.Length == 3 && double.TryParse(p[2], NumberStyles.Float, CI, out var q)) d[p[1]] = (d.TryGetValue(p[1], out var a) ? a : 0) + q;
            }
            return d;
        }

        public static object Registrar(Config cfg, PedidoMetrado ped)
        {
            var b = Datos.Base(cfg);
            if (!DateTime.TryParseExact(ped?.fecha ?? "", "yyyy-MM-dd", CI, DateTimeStyles.None, out var fecha)) throw new Exception("Fecha no válida (aaaa-mm-dd).");
            var partidas = b["partidas"].AsArray().ToDictionary(p => (string)p["item"], p => p);
            var conElementos = new HashSet<string>();
            var elems = new Dictionary<long, JsonNode>();
            foreach (var n in b["elementos"].AsArray())
            {
                elems[(long)n["id"]] = n;
                foreach (var p in n["partidas"].AsArray()) conElementos.Add((string)p["item"]);
            }
            var aplicados = new List<object>(); var rechazados = new List<object>(); var alertas = new List<string>();
            var tocados = new HashSet<long>();
            string f = fecha.ToString("yyyy-MM-dd"), fdmy = fecha.ToString("dd/MM/yyyy");

            lock (Candado)
            {
                var reg = Leer(cfg);
                var E = reg["elementos"].AsObject();
                foreach (var r in ped.registros ?? new List<Registro1>())
                {
                    if (r.cantidad == 0 || double.IsNaN(r.cantidad)) { rechazados.Add(new { r.id, r.item, motivo = "Cantidad 0 o no válida." }); continue; }
                    if (!partidas.TryGetValue(r.item ?? "", out var part)) { rechazados.Add(new { r.id, r.item, motivo = "La partida no existe en el presupuesto." }); continue; }
                    string und = (string)part["und"];
                    if (r.id == 0)
                    {
                        if (conElementos.Contains(r.item)) { rechazados.Add(new { r.id, r.item, motivo = "Esta partida tiene elementos: registra por elemento o por partida completa." }); continue; }
                        string g = (string)reg["global"] ?? "";
                        double ant = Sumas(g).TryGetValue(r.item, out var a0) ? a0 : 0, nuevo = ant + r.cantidad, contrato = (double)part["metrado"];
                        if (nuevo < -1e-9) { rechazados.Add(new { r.id, r.item, motivo = $"El acumulado quedaría negativo ({nuevo:0.###})." }); continue; }
                        reg["global"] = g + $"{f}|{r.item}|{r.cantidad.ToString("R", CI)};";
                        if (nuevo > contrato * (1 + 1e-6) + 1e-9) alertas.Add($"{r.item}: acumulado {nuevo:0.###} {und} supera el contrato ({contrato:0.###} {und}).");
                        aplicados.Add(new { r.id, r.item, r.cantidad, acumulado = nuevo, contrato });
                        continue;
                    }
                    if (!elems.TryGetValue(r.id, out var de)) { rechazados.Add(new { r.id, r.item, motivo = "El elemento no está en los datos del cronograma." }); continue; }
                    var pe = de["partidas"].AsArray().FirstOrDefault(p => (string)p["item"] == r.item);
                    if (pe == null) { rechazados.Add(new { r.id, r.item, motivo = "Esa partida no corresponde a este elemento." }); continue; }
                    var clave = r.id.ToString(CI);
                    var nodo = E[clave]?.AsObject() ?? new JsonObject { ["registro"] = "", ["obs"] = "" };
                    string regE = (string)nodo["registro"] ?? "";
                    double antE = Sumas(regE).TryGetValue(r.item, out var a1) ? a1 : 0, nuevoE = antE + r.cantidad, contE = (double)pe["metrado"];
                    if (nuevoE < -1e-9) { rechazados.Add(new { r.id, r.item, motivo = $"El acumulado quedaría negativo ({nuevoE:0.###})." }); continue; }
                    nodo["registro"] = regE + $"{f}|{r.item}|{r.cantidad.ToString("R", CI)};";
                    if (nuevoE > contE * (1 + 1e-6) + 1e-9)
                    {
                        string msg = $"{fdmy} · mayor metrado {r.item}: acumulado {nuevoE:0.###} {und} > contrato {contE:0.###} {und}";
                        alertas.Add($"Elemento {r.id} ({de["tipo"]}): {msg}");
                        string obs = (string)nodo["obs"] ?? "";
                        nodo["obs"] = (obs.Length > 0 ? obs + " | " : "") + msg;
                    }
                    E[clave] = nodo; tocados.Add(r.id);
                    aplicados.Add(new { r.id, r.item, r.cantidad, acumulado = nuevoE, contrato = contE });
                }
                if (!ped.simular && aplicados.Count > 0) Guardar(cfg, reg);
                Registro.Escribir($"Metrado {fdmy}: {aplicados.Count} aplicados, {rechazados.Count} rechazados, simular={ped.simular} (archivo del panel)");
                return new
                {
                    ok = true, simulado = ped.simular, guardado = !ped.simular && aplicados.Count > 0, aplicados, rechazados, alertas, notas = new List<string>(),
                    elementos = ped.simular ? new List<object>() : tocados.Select(id => (object)new { id, registro = (string)E[id.ToString(CI)]["registro"], obs = (string)E[id.ToString(CI)]["obs"] }).ToList(),
                    registroGlobal = (string)reg["global"] ?? ""
                };
            }
        }
    }
}
