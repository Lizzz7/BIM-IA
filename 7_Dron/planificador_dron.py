"""
Planificador de vuelo fotogramétrico - DJI Mini 5 Pro
Hackathon BIM + IA UNSA 2026

Calcula GSD, huella, espaciado, nº de fotos, tiempo y baterías para:
  1) malla nadir (90°)          -> ortomosaico, DSM, volúmenes
  2) doble malla oblicua (-60°) -> fachadas, columnas, bordes
  3) órbitas alrededor de la estructura
y exporta:
  - plan_vuelo.png        vista en planta del plan
  - waypoints_litchi.csv  para importar en Litchi Hub -> exportar KMZ -> DJI Fly
  - plan_vuelo.kml        para revisar en Google Earth
  - resumen_plan.json     para mostrar en el dashboard

Uso:
  python planificador_dron.py --lat -16.4045 --lon -71.5240 --ancho 80 --largo 80 \
         --altura 30 --altura-edif 12
"""
import argparse, json, math, csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# ---------- Cámara DJI Mini 5 Pro (sensor 1", 50 MP, 4:3, FOV 84° diagonal) ----------
SENSOR_W_MM = 13.2
SENSOR_H_MM = 9.9          # recorte 4:3 del sensor de 1"
IMG_W_50, IMG_H_50 = 8192, 6144
IMG_W_12, IMG_H_12 = 4096, 3072
FOV_DIAG = 84.0
FOCAL_MM = (math.hypot(SENSOR_W_MM, SENSOR_H_MM) / 2) / math.tan(math.radians(FOV_DIAG / 2))

R_TIERRA = 6378137.0


def huella(alt):
    """Huella de una foto nadir en el suelo (ancho x alto, en m)."""
    return SENSOR_W_MM * alt / FOCAL_MM, SENSOR_H_MM * alt / FOCAL_MM


def gsd_cm(alt, img_w):
    return SENSOR_W_MM * alt * 100 / (FOCAL_MM * img_w)


def offset(lat, lon, dx, dy):
    """Desplaza (dx este, dy norte) metros desde lat/lon."""
    dlat = dy / R_TIERRA
    dlon = dx / (R_TIERRA * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lon + math.degrees(dlon)


def malla(ancho, largo, alt, solape_f, solape_l, margen, direccion="NS"):
    """Devuelve líneas de vuelo [(x0,y0,x1,y1)] y nº de fotos. Coordenadas locales en m."""
    hw, hh = huella(alt)                 # lado largo de la foto perpendicular al avance
    paso_lineas = hw * (1 - solape_l)
    paso_fotos = hh * (1 - solape_f)
    W, L = ancho + 2 * margen, largo + 2 * margen
    if direccion == "EO":
        W, L = L, W
    n_lineas = math.ceil(W / paso_lineas) + 1
    fotos_linea = math.ceil(L / paso_fotos) + 1
    lineas = []
    for i in range(n_lineas):
        x = -W / 2 + i * paso_lineas
        y0, y1 = (-L / 2, L / 2) if i % 2 == 0 else (L / 2, -L / 2)
        lineas.append((y0, x, y1, x) if direccion == "EO" else (x, y0, x, y1))
    return lineas, n_lineas * fotos_linea, paso_lineas, paso_fotos


def longitud(lineas):
    tot = 0
    for i, (x0, y0, x1, y1) in enumerate(lineas):
        tot += math.hypot(x1 - x0, y1 - y0)
        if i:
            px, py = lineas[i - 1][2], lineas[i - 1][3]
            tot += math.hypot(x0 - px, y0 - py)
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=-16.4045, help="centro de la obra")
    ap.add_argument("--lon", type=float, default=-71.5240)
    ap.add_argument("--ancho", type=float, default=80, help="m, eje E-O")
    ap.add_argument("--largo", type=float, default=80, help="m, eje N-S")
    ap.add_argument("--altura", type=float, default=30, help="altura de vuelo (m)")
    ap.add_argument("--altura-edif", type=float, default=12, help="altura máx. de la estructura (m)")
    ap.add_argument("--solape-f", type=float, default=0.80)
    ap.add_argument("--solape-l", type=float, default=0.70)
    ap.add_argument("--margen", type=float, default=15)
    ap.add_argument("--intervalo", type=float, default=3.0, help="s entre fotos (modo intervalo)")
    ap.add_argument("--bateria-util-min", type=float, default=22, help="min útiles por batería")
    a = ap.parse_args()

    alt_rel = a.altura  # sobre el punto de despegue
    if alt_rel < a.altura_edif + 15:
        print(f"⚠ Altura {alt_rel} m muy cerca de la estructura ({a.altura_edif} m). Se recomienda ≥ {a.altura_edif+15} m.")

    # 1) malla nadir
    nadir, f_nadir, pl, pf = malla(a.ancho, a.largo, alt_rel, a.solape_f, a.solape_l, a.margen, "NS")
    vel = min(pf / a.intervalo, 5.0)
    # 2) doble malla oblicua (misma geometría, cámara a -60°, dos direcciones)
    obl1, f_o1, _, _ = malla(a.ancho, a.largo, alt_rel, a.solape_f, a.solape_l, a.margen / 2, "NS")
    obl2, f_o2, _, _ = malla(a.ancho, a.largo, alt_rel, a.solape_f, a.solape_l, a.margen / 2, "EO")
    # 3) órbitas: radio = media diagonal de la obra + 10 m, foto cada 10°
    radio = math.hypot(a.ancho, a.largo) / 2 + 10
    orbitas = [(a.altura_edif + 10, -30), (a.altura_edif + 20, -45)]
    f_orb = 36 * len(orbitas)

    def minutos(lineas, n_fotos):
        return (longitud(lineas) / vel) / 60 + 1.5  # +1.5 min despegue/regreso

    t_nadir = minutos(nadir, f_nadir)
    t_obl = minutos(obl1, f_o1) + minutos(obl2, f_o2)
    t_orb = sum(2 * math.pi * radio / 3.0 for _ in orbitas) / 60 + 1.5
    t_total = t_nadir + t_obl + t_orb
    fotos = f_nadir + f_o1 + f_o2 + f_orb
    hw, hh = huella(alt_rel)

    resumen = {
        "dron": "DJI Mini 5 Pro",
        "altura_vuelo_m": alt_rel,
        "gsd_cm_px_50MP": round(gsd_cm(alt_rel, IMG_W_50), 2),
        "gsd_cm_px_12MP": round(gsd_cm(alt_rel, IMG_W_12), 2),
        "huella_foto_m": [round(hw, 1), round(hh, 1)],
        "separacion_lineas_m": round(pl, 1),
        "separacion_fotos_m": round(pf, 1),
        "velocidad_m_s": round(vel, 1),
        "intervalo_foto_s": a.intervalo,
        "misiones": {
            "1_nadir_90": {"fotos": f_nadir, "lineas": len(nadir), "min": round(t_nadir, 1)},
            "2_oblicua_-60_doble_malla": {"fotos": f_o1 + f_o2, "min": round(t_obl, 1)},
            "3_orbitas": {"fotos": f_orb, "radio_m": round(radio, 1),
                          "alturas_m": [o[0] for o in orbitas], "pitch": [o[1] for o in orbitas],
                          "min": round(t_orb, 1)},
        },
        "fotos_totales": fotos,
        "minutos_totales": round(t_total, 1),
        "baterias": math.ceil(t_total / a.bateria_util_min),
        "datos_GB_aprox_50MP": round(fotos * 0.022, 1),
    }
    with open("resumen_plan.json", "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)

    # ---------- CSV para Litchi Hub (malla nadir + oblicuas) ----------
    cab = ["latitude", "longitude", "altitude(m)", "heading(deg)", "curvesize(m)", "rotationdir",
           "gimbalmode", "gimbalpitchangle"]
    for k in range(1, 16):
        cab += [f"actiontype{k}", f"actionparam{k}"]
    cab += ["altitudemode", "speed(m/s)", "poi_latitude", "poi_longitude", "poi_altitude(m)",
            "poi_altitudemode", "photo_timeinterval", "photo_distinterval"]

    def filas(lineas, pitch):
        out = []
        for (x0, y0, x1, y1) in lineas:
            heading = (math.degrees(math.atan2(x1 - x0, y1 - y0)) + 360) % 360
            for (x, y) in ((x0, y0), (x1, y1)):
                la, lo = offset(a.lat, a.lon, x, y)
                fila = [f"{la:.7f}", f"{lo:.7f}", alt_rel, round(heading), 0, 0, 2, pitch]
                fila += [-1, 0] * 15
                fila += [0, round(vel, 1), 0, 0, 0, 0, -1, round(pf, 1)]
                out.append(fila)
        return out

    with open("waypoints_litchi.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cab)
        w.writerows(filas(nadir, -90))
    with open("waypoints_litchi_oblicua.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cab)
        w.writerows(filas(obl1, -60) + filas(obl2, -60))

    # ---------- KML ----------
    def kml_linea(nombre, lineas, color):
        coords = []
        for (x0, y0, x1, y1) in lineas:
            for (x, y) in ((x0, y0), (x1, y1)):
                la, lo = offset(a.lat, a.lon, x, y)
                coords.append(f"{lo:.7f},{la:.7f},{alt_rel}")
        return (f"<Placemark><name>{nombre}</name><Style><LineStyle><color>{color}</color>"
                f"<width>2</width></LineStyle></Style><LineString><altitudeMode>relativeToGround"
                f"</altitudeMode><coordinates>{' '.join(coords)}</coordinates></LineString></Placemark>")

    ring = []
    for (x, y) in [(-a.ancho/2, -a.largo/2), (a.ancho/2, -a.largo/2), (a.ancho/2, a.largo/2),
                   (-a.ancho/2, a.largo/2), (-a.ancho/2, -a.largo/2)]:
        la, lo = offset(a.lat, a.lon, x, y)
        ring.append(f"{lo:.7f},{la:.7f},0")
    with open("plan_vuelo.kml", "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>')
        f.write(f"<Placemark><name>Obra</name><Polygon><outerBoundaryIs><LinearRing><coordinates>{' '.join(ring)}"
                "</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>")
        f.write(kml_linea("Nadir 90°", nadir, "ff00ffff"))
        f.write(kml_linea("Oblicua NS -60°", obl1, "ff0080ff"))
        f.write(kml_linea("Oblicua EO -60°", obl2, "ffff8000"))
        f.write("</Document></kml>")

    # ---------- Figura ----------
    fig, axs = plt.subplots(1, 2, figsize=(14, 7))
    for ax, (tit, conj) in zip(axs, [("1) Malla nadir 90°", [(nadir, "#1f77b4")]),
                                     ("2) Doble malla oblicua -60° + 3) órbitas",
                                      [(obl1, "#ff7f0e"), (obl2, "#2ca02c")])]):
        ax.add_patch(Rectangle((-a.ancho/2, -a.largo/2), a.ancho, a.largo, fc="#ddd", ec="k", label="Obra"))
        for lineas, c in conj:
            xs, ys = [], []
            for (x0, y0, x1, y1) in lineas:
                xs += [x0, x1]; ys += [y0, y1]
            ax.plot(xs, ys, "-", color=c, lw=1.2)
            if lineas is nadir:
                for (x0, y0, x1, y1) in lineas:
                    n = int(math.hypot(x1-x0, y1-y0) / pf) + 1
                    for k in range(n):
                        t = k / max(n-1, 1)
                        ax.plot(x0+(x1-x0)*t, y0+(y1-y0)*t, ".", color="k", ms=2)
        if "órbitas" in tit:
            th = [i * 2 * math.pi / 36 for i in range(37)]
            ax.plot([radio*math.cos(t) for t in th], [radio*math.sin(t) for t in th], "r--", lw=1.5, label="Órbita")
            ax.plot([radio*math.cos(t) for t in th[:-1]], [radio*math.sin(t) for t in th[:-1]], "r.", ms=4)
        ax.set_aspect("equal"); ax.grid(alpha=.3); ax.set_title(tit)
        ax.set_xlabel("Este (m)"); ax.set_ylabel("Norte (m)")
        ax.legend(loc="upper right", fontsize=8)
    fig.suptitle(f"DJI Mini 5 Pro · {alt_rel:.0f} m · GSD {resumen['gsd_cm_px_50MP']} cm/px (50 MP) · "
                 f"{fotos} fotos · {resumen['minutos_totales']} min · {resumen['baterias']} baterías", fontsize=12)
    plt.tight_layout()
    plt.savefig("plan_vuelo.png", dpi=130)

    print(json.dumps(resumen, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
