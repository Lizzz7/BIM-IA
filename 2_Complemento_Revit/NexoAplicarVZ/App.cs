// NEXO OBRA (NO) · Aplica UNA VEZ los valores de planificación y metrado VZ_ (lo mismo que hace Cargar_Parametros_NEXO_NO.dyn
// en sus pasos 2-3) desde parametros_revit_<modelo>.json. No toca fechas de ejecución, registros ni observaciones.
// Escribe nexo_aplicar_vz.log y un archivo .hecho para no repetirse. Se ejecuta en el primer momento libre de Revit.
using System;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;

namespace NexoAplicarVZ
{
    public class App : IExternalApplication
    {
        static string Dir => Path.GetDirectoryName(typeof(App).Assembly.Location);
        static void Log(string m) { try { File.AppendAllText(Path.Combine(Dir, "nexo_aplicar_vz.log"), DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + m + Environment.NewLine); } catch { } }
        static UIControlledApplication uic;

        public Result OnStartup(UIControlledApplication a) { uic = a; a.Idling += Una; Log("Cargado"); return Result.Succeeded; }
        public Result OnShutdown(UIControlledApplication a) => Result.Succeeded;

        static void Una(object s, IdlingEventArgs e)
        {
            uic.Idling -= Una;
            try
            {
                var cfg = JsonNode.Parse(File.ReadAllText(Path.Combine(Dir, "aplicar.json")).TrimStart('﻿'));
                var marca = Path.Combine(Dir, (string)cfg["clave"] + ".hecho");
                if (File.Exists(marca)) { Log("Ya aplicado antes: " + marca); return; }
                var doc = (s as UIApplication)?.ActiveUIDocument?.Document;
                var datos = JsonNode.Parse(File.ReadAllText((string)cfg["datos"]));
                string modelo = (string)datos["modelo"];
                if (doc == null || !string.Equals(Path.GetFileNameWithoutExtension(doc.PathName), modelo, StringComparison.OrdinalIgnoreCase))
                { Log("El modelo activo no es " + modelo + "; no se aplica."); return; }
                int ok = 0, falta = 0, sinParam = 0;
                using (var t = new Transaction(doc, "NEXO OBRA: actualizar parámetros VZ_ (presupuesto v3)"))
                {
                    t.Start();
                    foreach (var n in datos["elementos"].AsArray())
                    {
                        var el = doc.GetElement(new ElementId((long)n["id"]));
                        if (el == null) { falta++; continue; }
                        double monto = Math.Round((double)n["monto_concreto"] + (double)n["monto_encofrado"] + (double)n["monto_acero"], 2);
                        bool b = Poner(el, "VZ_Paquete", (string)n["paquete"]) & Poner(el, "VZ_Sector", (string)n["sector"]) &
                                 Poner(el, "VZ_Actividad", (string)n["actividad"]) & Poner(el, "VZ_Partida", (string)n["partida"]) &
                                 Poner(el, "VZ_Fecha_Prog", (string)n["fecha_prog"]) &
                                 Poner(el, "VZ_Concreto_m3", UnitUtils.ConvertToInternalUnits((double)n["concreto_m3"], UnitTypeId.CubicMeters)) &
                                 Poner(el, "VZ_Encofrado_m2", UnitUtils.ConvertToInternalUnits((double)n["encofrado_m2"], UnitTypeId.SquareMeters)) &
                                 Poner(el, "VZ_Acero_kg", (double)n["acero_kg"]) & Poner(el, "VZ_Monto_Contractual", monto);
                        if (b) ok++; else sinParam++;
                    }
                    t.Commit();
                }
                File.WriteAllText(marca, DateTime.Now.ToString("s"));
                Log($"Aplicado: {ok} elementos actualizados, {falta} no encontrados, {sinParam} con algún parámetro faltante.");
            }
            catch (Exception ex) { Log("ERROR: " + ex); }
        }

        static bool Poner(Element e, string nombre, object v)
        {
            var p = e.LookupParameter(nombre);
            if (p == null || p.IsReadOnly) return false;
            if (p.StorageType == StorageType.String) return p.Set(Convert.ToString(v));
            if (p.StorageType == StorageType.Double) return p.Set(Convert.ToDouble(v));
            if (p.StorageType == StorageType.Integer) return p.Set(Convert.ToInt32(v));
            return false;
        }
    }
}
