"""Genera una nube de puntos SIMULADA desde el IFC del proyecto, tal como la entregaría WebODM:
en coordenadas compartidas/UTM, con color, oclusión desde el plan de vuelo y efectos de fotogrametría.
Junto a la nube escribe la VERDAD (qué está construido) para validar el comparador.

Uso (desde la raíz del repo):
  python3 7_Dron/nube_desde_ifc.py --ifc ruta/al/modelo.ifc --fecha 2027-09-30 --salida vuelo_simulado.ply
Luego, en el panel: Parte diario › Avance por dron › subir primero el .ifc y después vuelo_simulado.ply.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "nexo-ia"))
os.environ.setdefault("NEXO_REPO", str(RAIZ))
os.environ.setdefault("NEXO_ESTADO", tempfile.mkdtemp(prefix="nube_ifc_"))

from nexo_ia import datos as D, ifc_modelo, nube_io, sintetico  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ifc", required=True)
    ap.add_argument("--fecha", default="2027-09-30", help="fecha de corte: está construido lo programado hasta aquí")
    ap.add_argument("--salida", default="vuelo_simulado.ply")
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--ruido", type=float, default=0.02)
    ap.add_argument("--huecos", type=float, default=0.15)
    ap.add_argument("--coords-modelo", action="store_true", help="salida en coordenadas internas del modelo (no UTM)")
    a = ap.parse_args()

    D.usar()
    info = ifc_modelo.cargar(Path(a.ifc).read_bytes(), Path(a.ifc).name)
    print(f"IFC: {info['elementos_comunes']}/{info['elementos_panel']} elementos cruzados · giro {info['giro_grados']}° · "
          f"residuo {info['residuo_mediano_m']*1000:.1f} mm")
    nube, verdad, _, rgb = sintetico.generar(a.fecha, semilla=a.semilla, ruido=a.ruido, huecos=a.huecos,
                                             desde_ifc=True, coords_ifc=not a.coords_modelo)
    nube_io.escribir_ply(a.salida, nube, rgb)
    Path(a.salida).with_suffix(".verdad.json").write_text(json.dumps(verdad, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(nube):,} puntos -> {a.salida} ({Path(a.salida).stat().st_size/2**20:.0f} MB) · "
          f"{len(verdad['construidos'])} elementos construidos, {len(verdad['retrasados'])} retrasados, "
          f"{len(verdad['falsos_registrados'])} registros falsos sembrados · verdad en {Path(a.salida).with_suffix('.verdad.json').name}")


if __name__ == "__main__":
    main()
