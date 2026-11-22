"""Empaqueta una versión del modelo para publicarla (el paso «Publicar versión», hoy sin cambiar el complemento).

Toma lo que ya exportan el complemento y los scripts del repo y arma un zip con manifiesto:
    modelo.json  instantanea.html  cronograma.json  metrados.json  auditoria.json  parametros.json  [presupuesto.xlsx]

Uso:
  python3 empaquetar_version.py --repo ../BIM-IA --rvt REP0-MOD2-R02 --id REP0-MOD2 --version R02 \
          --autor "Modelador" --comentario "Corregí placas del eje 3"
  # publicar en el servidor (necesita NEXO_TOKEN_ADMIN):
  curl -X POST --data-binary @REP0-MOD2_R02.zip -H "X-Nexo-Admin: $NEXO_TOKEN_ADMIN" https://<servidor>/api/admin/publicar
"""
import argparse
import json
import time
import zipfile
from pathlib import Path


def empaquetar(repo: Path, rvt: str, mid: str, version: str, autor: str, comentario: str, salida: Path = None):
    fuentes = {
        "instantanea": (repo / "5_Documentacion" / "Compartir" / "NEXO_OBRA_solo_lectura.html", "instantanea.html"),
        "cronograma": (repo / "1_Panel" / "datos" / "nexo_no_datos.json", "cronograma.json"),
        "metrados": (repo / "3_Modelo_y_parametros" / f"metrados_{rvt}.json", "metrados.json"),
        "auditoria": (repo / "3_Modelo_y_parametros" / f"auditoria_{rvt}.json", "auditoria.json"),
        "parametros": (repo / "3_Modelo_y_parametros" / f"parametros_revit_{rvt}.json", "parametros.json"),
        "presupuesto": (repo / "5_Documentacion" / f"Presupuesto_Estructuras_{rvt}_v4.xlsx", "presupuesto.xlsx"),
    }
    faltan = [str(p) for k, (p, _) in fuentes.items() if k != "presupuesto" and not p.exists()]
    if faltan:
        raise SystemExit("Faltan archivos exportados:\n  " + "\n  ".join(faltan))
    man = {"id": mid, "version": version, "nombre": mid, "archivo_revit": rvt, "autor": autor, "comentario": comentario,
           "publicado": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "archivos": {k: dest for k, (p, dest) in fuentes.items() if p.exists()}}
    salida = salida or Path(f"{mid}_{version}.zip")
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("modelo.json", json.dumps(man, ensure_ascii=False, indent=1))
        for k, (p, dest) in fuentes.items():
            if p.exists():
                z.write(p, dest)
    return salida


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--repo", default="../BIM-IA")
    a.add_argument("--rvt", default="REP0-MOD2-R02", help="nombre del archivo de Revit (sin .rvt)")
    a.add_argument("--id", required=True, help="id del modelo (obra/especialidad), p. ej. REP0-MOD2")
    a.add_argument("--version", required=True, help="p. ej. R02, R03, 2027-03-15")
    a.add_argument("--autor", default="")
    a.add_argument("--comentario", default="")
    x = a.parse_args()
    print(empaquetar(Path(x.repo), x.rvt, x.id, x.version, x.autor, x.comentario))
