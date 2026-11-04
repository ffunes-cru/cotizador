"""@file
Análisis de complejidad ciclomática de todas las funciones del módulo (Python y JavaScript).

Mide cada función con [lizard](https://github.com/terryyin/lizard) y reescribe la parte generada de
docs/mantenibilidad.md (entre los marcadores INICIO y FIN); el análisis escrito a mano queda intacto.
No importa Odoo: se corre suelto, desde la carpeta del módulo:

    uv run --no-project --with lizard==1.25.0 python tools/complejidad.py

lizard no es dependencia del módulo (Odoo nunca importa este archivo), por eso no hay test que exija
que el documento esté al día: regenerarlo al cambiar código y commitearlo junto.
"""
import sys
from collections import Counter
from pathlib import Path

## Carpeta raíz del módulo.
RAIZ = Path(__file__).resolve().parent.parent
## Documento con la parte generada.
ARCHIVO = RAIZ / 'docs' / 'mantenibilidad.md'
## Marcador donde empieza la parte generada.
INICIO = '<!-- complejidad:inicio (generado por tools/complejidad.py, no editar a mano) -->'
## Marcador donde termina la parte generada.
FIN = '<!-- complejidad:fin -->'
## Áreas del módulo: (nombre, carpetas relativas a la raíz, patrón de archivos).
AREAS = (
    ('Servidor', ('models', 'controllers', 'tools'), '*.py'),
    ('Navegador', ('static/src',), '*.js'),
    ('Tests', ('tests',), '*.py'),
    ('Tests', ('static/tests',), '*.js'),
    ('Herramientas de escritorio', ('scripts',), '*.py'),
)
## Rangos de complejidad: (letra, máximo inclusivo, significado). Escala de radon / McCabe.
RANGOS = (
    ('A', 5, 'simple'),
    ('B', 10, 'bien estructurada'),
    ('C', 20, 'compleja'),
    ('D', 30, 'muy compleja'),
    ('E', 40, 'alarmante'),
    ('F', None, 'inmantenible'),
)
## Complejidad a partir de la cual una función entra en la lista de atención (rango C o peor).
UMBRAL = 10


def rango(ccn):
    """Letra del rango de una complejidad ciclomática.

    @param ccn Complejidad ciclomática de la función.
    @return 'A' a 'F' según RANGOS.
    """
    for letra, maximo, _significado in RANGOS:
        if maximo is None or ccn <= maximo:
            return letra
    return RANGOS[-1][0]


def analizar():
    """Mide todas las funciones del módulo.

    @return Lista de dicts `{area, archivo, linea, fin, nombre, ccn, rango, nloc, parametros}`,
            ordenada por archivo y línea. `nloc` son líneas de código sin comentarios ni blancos.
    @throws SystemExit Si lizard no está instalado.
    """
    try:
        import lizard
    except ImportError:
        sys.exit("Falta lizard: uv run --no-project --with lizard==1.25.0 python tools/complejidad.py")
    funciones = []
    for area, carpetas, patron in AREAS:
        for carpeta in carpetas:
            for archivo in sorted((RAIZ / carpeta).rglob(patron)):
                if '__pycache__' in archivo.parts:
                    continue
                relativo = archivo.relative_to(RAIZ).as_posix()
                for funcion in lizard.analyze_file(str(archivo)).function_list:
                    funciones.append({
                        'area': area,
                        'archivo': relativo,
                        'linea': funcion.start_line,
                        'fin': funcion.end_line,
                        'nombre': '(anónima)' if funcion.name == '(anonymous)' else funcion.name,
                        'ccn': funcion.cyclomatic_complexity,
                        'rango': rango(funcion.cyclomatic_complexity),
                        'nloc': funcion.nloc,
                        'parametros': funcion.parameter_count,
                    })
    return sorted(funciones, key=lambda f: (f['archivo'], f['linea']))


def _enlace(funcion):
    """Enlace Markdown a la función, relativo a docs/.

    @param funcion Dict de analizar().
    @return Texto `[archivo:línea](../archivo#Llínea)`.
    """
    return f"[{funcion['archivo']}:{funcion['linea']}](../{funcion['archivo']}#L{funcion['linea']})"


def _resumen(funciones):
    """Totales de un grupo de funciones.

    @param funciones Lista de dicts de analizar().
    @return Dict `{n, nloc, promedio, maximo, atencion, rangos}`; `atencion` cuenta las de CCN > UMBRAL
            y `rangos` es un Counter por letra.
    """
    ccns = [f['ccn'] for f in funciones]
    return {
        'n': len(funciones),
        'nloc': sum(f['nloc'] for f in funciones),
        'promedio': sum(ccns) / len(ccns) if ccns else 0.0,
        'maximo': max(ccns, default=0),
        'atencion': sum(1 for c in ccns if c > UMBRAL),
        'rangos': Counter(f['rango'] for f in funciones),
    }


def _tabla_areas(funciones):
    """Resumen por área, con la distribución de rangos.

    @param funciones Lista de dicts de analizar().
    @return Líneas Markdown.
    """
    letras = [letra for letra, _maximo, _significado in RANGOS]
    salida = ['## Resumen por área', '',
              '| Área | Funciones | Líneas de código | CCN promedio | CCN máxima | CCN > 10 | '
              + ' | '.join(letras) + ' |',
              '|---|--:|--:|--:|--:|--:|' + '--:|' * len(letras)]
    grupos = [(area, [f for f in funciones if f['area'] == area]) for area in dict.fromkeys(a for a, _c, _p in AREAS)]
    for area, grupo in grupos + [('**Total**', funciones)]:
        r = _resumen(grupo)
        salida.append(f"| {area} | {r['n']} | {r['nloc']} | {r['promedio']:.1f} | {r['maximo']} | "
                      f"{r['atencion']} | " + ' | '.join(str(r['rangos'][letra]) for letra in letras) + ' |')
    return salida


def _tabla_atencion(funciones):
    """Funciones con CCN mayor que UMBRAL, de mayor a menor.

    @param funciones Lista de dicts de analizar().
    @return Líneas Markdown.
    """
    salida = [f'## Funciones que requieren atención (CCN > {UMBRAL})', '',
              'Ordenadas de mayor a menor complejidad.', '',
              '| CCN | Rango | Función | Ubicación | Líneas de código | Parámetros |',
              '|--:|:-:|---|---|--:|--:|']
    atencion = sorted((f for f in funciones if f['ccn'] > UMBRAL), key=lambda f: (-f['ccn'], f['archivo'], f['linea']))
    for f in atencion:
        salida.append(f"| {f['ccn']} | {f['rango']} | `{f['nombre']}` | {_enlace(f)} | {f['nloc']} | {f['parametros']} |")
    return salida


def _por_archivo(funciones):
    """Funciones agrupadas por archivo, en orden de archivo.

    @param funciones Lista de dicts de analizar() (ya ordenada por archivo y línea).
    @return Lista de tuplas `(archivo, funciones del archivo)`.
    """
    grupos = {}
    for f in funciones:
        grupos.setdefault(f['archivo'], []).append(f)
    return list(grupos.items())


def _tabla_archivos(funciones):
    """Resumen por archivo.

    @param funciones Lista de dicts de analizar().
    @return Líneas Markdown.
    """
    salida = ['## Por archivo', '',
              '| Archivo | Funciones | Líneas de código | CCN promedio | CCN máxima | Peor rango | CCN > 10 |',
              '|---|--:|--:|--:|--:|:-:|--:|']
    for archivo, grupo in _por_archivo(funciones):
        r = _resumen(grupo)
        salida.append(f"| [{archivo}](../{archivo}) | {r['n']} | {r['nloc']} | {r['promedio']:.1f} | "
                      f"{r['maximo']} | {rango(r['maximo'])} | {r['atencion']} |")
    return salida


def _tabla_funciones(funciones):
    """Todas las funciones, un bloque plegable por archivo.

    @param funciones Lista de dicts de analizar().
    @return Líneas Markdown.
    """
    salida = ['## Todas las funciones', '',
              'Por archivo y en orden de aparición. Las funciones anónimas de JavaScript (callbacks) se '
              'miden aparte de la función que las contiene.']
    for archivo, grupo in _por_archivo(funciones):
        salida += ['', f"<details><summary><code>{archivo}</code> — {len(grupo)} funciones, "
                   f"CCN máxima {_resumen(grupo)['maximo']}</summary>", '',
                   '| Línea | Función | CCN | Rango | Líneas de código | Parámetros |',
                   '|--:|---|--:|:-:|--:|--:|']
        salida += [f"| [{f['linea']}](../{archivo}#L{f['linea']}) | `{f['nombre']}` | {f['ccn']} | "
                   f"{f['rango']} | {f['nloc']} | {f['parametros']} |" for f in grupo]
        salida += ['', '</details>']
    return salida


def generar(funciones):
    """Arma la parte generada del documento.

    @param funciones Lista de dicts de analizar().
    @return Markdown (sin los marcadores).
    """
    secciones = (_tabla_areas, _tabla_atencion, _tabla_archivos, _tabla_funciones)
    return '\n\n'.join('\n'.join(seccion(funciones)) for seccion in secciones)


def escribir():
    """Reemplaza la parte generada de docs/mantenibilidad.md.

    @throws SystemExit Si el documento no tiene los marcadores INICIO y FIN.
    """
    texto = ARCHIVO.read_text(encoding='utf-8')
    if INICIO not in texto or FIN not in texto:
        sys.exit(f"{ARCHIVO} no tiene los marcadores de la parte generada.")
    antes, resto = texto.split(INICIO, 1)
    _generado, despues = resto.split(FIN, 1)
    ARCHIVO.write_text(f"{antes}{INICIO}\n\n{generar(analizar())}\n\n{FIN}{despues}", encoding='utf-8')


if __name__ == '__main__':
    escribir()
