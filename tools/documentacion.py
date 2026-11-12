"""@file
Herramientas de documentación del módulo: verificación de docstrings y referencia generada.

1. **Docstrings** (faltantes()): todo módulo, clase y función de Python, y toda clase, método y
   función de JavaScript, tiene comentario de documentación; cada parámetro tiene `@param` y
   cada función de Python que devuelve un valor tiene `@return`. Es el formato que lee Doxygen
   (docs/Doxyfile). El test tests/test_documentacion.py falla si falta algo.

2. **Referencia** (generar() / escribir()): docs/referencia.md se arma con los metadatos del
   ORM (modelos, campos, permisos, reglas) y los archivos del módulo (quién llama a cada método:
   botones, JS, Python), así no se desactualiza. El mismo test falla si quedó vieja.

Regenerar la referencia (y commitear docs/referencia.md):

    ./odoo-bin shell -d <base> --no-http <<< "from odoo.addons.cotizador.tools.documentacion import escribir; escribir(env)"
"""
import ast
import inspect
import re
from pathlib import Path

from lxml import etree

from odoo import models

## Nombre técnico del módulo.
MODULO = 'cotizador'
## Carpeta raíz del módulo.
RAIZ = Path(__file__).resolve().parent.parent
## Archivo de la referencia generada.
ARCHIVO = RAIZ / 'docs' / 'referencia.md'
## Carpetas con código Python propio (se excluye tests/, cuyos archivos se documentan con su nombre).
CARPETAS_PY = ('', 'models', 'controllers', 'tools')
## Carpetas con JavaScript propio.
CARPETAS_JS = ('static/src', 'static/tests')
## Prefijos de los modelos propios del módulo (los heredados se listan aparte).
PREFIJOS_MODELO = ('sembradora.', 'cotizador.', 'engineering.code.', 'equipo.usado.', 'product.template.description.')
## Tipos de campo relacionales.
RELACIONALES = ('many2one', 'one2many', 'many2many')
## `orm.call("modelo", "método"` en JavaScript.
JS_ORM_CALL = re.compile(r'orm\.call\(\s*["\']([\w.]+)["\'],\s*["\'](\w+)["\']')


# =============================================================================
#  1. Docstrings
# =============================================================================

def _archivos(carpetas, patron):
    """Archivos del módulo que coinciden con un patrón, en orden.

    @param carpetas Carpetas relativas a la raíz ('' = solo la raíz, sin subcarpetas).
    @param patron Patrón glob de los archivos, p. ej. '*.py'.
    @return Lista de Path.
    """
    archivos = []
    for carpeta in carpetas:
        base = RAIZ / carpeta
        archivos += sorted(base.glob(patron) if carpeta == '' else base.rglob(patron))
    return [a for a in archivos if '__pycache__' not in a.parts]


def _devuelve_valor(funcion):
    """Indica si una función de Python tiene algún `return <valor>` propio (sin contar funciones anidadas).

    @param funcion Nodo ast.FunctionDef.
    @return True si devuelve un valor distinto de None.
    """
    pendientes = list(funcion.body)
    while pendientes:
        nodo = pendientes.pop()
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(nodo, ast.Return) and nodo.value is not None and not (
                isinstance(nodo.value, ast.Constant) and nodo.value.value is None):
            return True
        pendientes.extend(ast.iter_child_nodes(nodo))
    return False


def _faltantes_funcion_py(funcion, donde):
    """Problemas de documentación de una función o método de Python.

    @param funcion Nodo ast.FunctionDef.
    @param donde Prefijo "archivo:línea" para los mensajes.
    @return Lista de mensajes.
    """
    doc = ast.get_docstring(funcion)
    if not doc:
        return [f"{donde}: {funcion.name}() sin docstring"]
    errores = []
    args = funcion.args
    nombres = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    nombres += [a.arg for a in (args.vararg, args.kwarg) if a]
    for nombre in nombres:
        if nombre not in ('self', 'cls') and not re.search(rf'@param\s+{nombre}\b', doc):
            errores.append(f"{donde}: {funcion.name}() sin @param {nombre}")
    if _devuelve_valor(funcion) and '@return' not in doc:
        errores.append(f"{donde}: {funcion.name}() sin @return")
    return errores


def faltantes_python():
    """Verifica la documentación de todo el Python del módulo.

    @return Lista de mensajes "archivo:línea: problema"; vacía si está todo documentado.
    """
    errores = []
    for archivo in _archivos(CARPETAS_PY, '*.py'):
        relativo = archivo.relative_to(RAIZ)
        if archivo.name == '__manifest__.py':
            continue
        arbol = ast.parse(archivo.read_text(encoding='utf-8'))
        if not (ast.get_docstring(arbol) or '').startswith('@file'):
            errores.append(f"{relativo}:1: el módulo no empieza con un docstring '@file'")
        for nodo in ast.walk(arbol):
            donde = f"{relativo}:{getattr(nodo, 'lineno', 1)}"
            if isinstance(nodo, ast.ClassDef) and not ast.get_docstring(nodo):
                errores.append(f"{donde}: clase {nodo.name} sin docstring")
            elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                errores += _faltantes_funcion_py(nodo, donde)
    return errores


## Definición de clase, método, getter/setter o función en JavaScript (una línea).
_JS_DEFINICION = re.compile(
    r'^(?P<indent>\s*)(?:export\s+)?(?:'
    r'class\s+(?P<clase>\w+)'
    r'|(?:async\s+)?function\s+(?P<funcion>\w+)\s*\((?P<args_f>[^)]*)\)'
    r'|(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?(?P<metodo>\w+)\s*\((?P<args_m>[^)]*)\)\s*\{'
    r')'
)
## Palabras que el patrón de métodos confundiría con un nombre de método.
_JS_NO_METODOS = {'if', 'for', 'while', 'switch', 'catch', 'function', 'return', 'super'}


def _nombres_parametros_js(args):
    """Nombres de los parámetros de una firma de JavaScript.

    @param args Texto entre paréntesis, p. ej. "group, line = null, ...rest".
    @return Lista de nombres (los desestructurados `{a, b}` no se exigen).
    """
    nombres = []
    for parte in args.split(','):
        parte = parte.strip().lstrip('.').split('=')[0].strip()
        if re.fullmatch(r'\w+', parte):
            nombres.append(parte)
    return nombres


def faltantes_js():
    """Verifica la documentación de todo el JavaScript del módulo.

    Exige un bloque de documentación `/**` inmediatamente antes de cada clase, método de clase (sangría
    de 4 espacios) y función de primer nivel, con `@param` para cada parámetro.

    @return Lista de mensajes "archivo:línea: problema"; vacía si está todo documentado.
    """
    errores = []
    for archivo in _archivos(CARPETAS_JS, '*.js'):
        relativo = archivo.relative_to(RAIZ)
        lineas = archivo.read_text(encoding='utf-8').splitlines()
        if not lineas or not lineas[0].startswith('/**') or '@file' not in '\n'.join(lineas[:5]):
            errores.append(f"{relativo}:1: el archivo no empieza con un bloque '/** @file'")
        for numero, linea in enumerate(lineas, start=1):
            definicion = _JS_DEFINICION.match(linea)
            if not definicion:
                continue
            indent = len(definicion['indent'])
            nombre = definicion['clase'] or definicion['funcion'] or definicion['metodo']
            if definicion['metodo'] and (indent != 4 or nombre in _JS_NO_METODOS):
                continue
            if (definicion['clase'] or definicion['funcion']) and indent != 0:
                continue
            anterior = numero - 2
            while anterior >= 0 and not lineas[anterior].strip():
                anterior -= 1
            if anterior < 0 or not lineas[anterior].strip().endswith('*/'):
                errores.append(f"{relativo}:{numero}: {nombre} sin bloque /** */")
                continue
            inicio = anterior
            while inicio > 0 and '/**' not in lineas[inicio]:
                inicio -= 1
            doc = '\n'.join(lineas[inicio:anterior + 1])
            for parametro in _nombres_parametros_js(definicion['args_f'] or definicion['args_m'] or ''):
                if not re.search(rf'@param\s+{parametro}\b', doc):
                    errores.append(f"{relativo}:{numero}: {nombre} sin @param {parametro}")
    return errores


def faltantes():
    """Todos los problemas de documentación del código (Python y JavaScript).

    @return Lista de mensajes; vacía si está todo documentado.
    """
    return faltantes_python() + faltantes_js()


# =============================================================================
#  2. Referencia generada
# =============================================================================

def generar(env):
    """Arma el contenido de docs/referencia.md.

    @param env Entorno de Odoo con el módulo instalado.
    @return Texto Markdown.
    """
    propios = sorted((env[nombre] for nombre in env.registry if nombre.startswith(PREFIJOS_MODELO)),
                     key=lambda m: m._name)
    heredados = sorted(
        (env[nombre] for nombre in env.registry
         if not nombre.startswith(PREFIJOS_MODELO) and _campos_propios(env[nombre])),
        key=lambda m: m._name)
    secciones = [
        '# Referencia generada del módulo Cotizador',
        '> Archivo generado por `tools/documentacion.py`: no editar a mano. '
        'Cómo regenerarlo: ver el encabezado de ese archivo.',
        '## Diagrama de datos',
        'Relaciones de los modelos propios (sin los asistentes). `}o--||` = muchos a uno obligatorio, '
        '`}o--o|` = muchos a uno opcional, `}o--o{` = muchos a muchos.',
        _diagrama([m for m in propios if not m._transient]),
        '## Modelos propios',
        *(_tabla_campos(m) for m in propios),
        '## Campos agregados a modelos de Odoo',
        *(_tabla_campos(m) for m in heredados),
        '## Puntos de entrada',
        'Métodos públicos (invocables por RPC) y quién los llama: botones de vistas, JavaScript '
        '(`orm.call`), Python y plantillas QWeb. Las llamadas desde código se buscan por nombre, así que '
        'un nombre repetido en otro modelo puede aparecer de más.',
        _puntos_de_entrada(env, propios + heredados),
        '## Permisos por modelo',
        'L = leer, E = escribir, C = crear, B = borrar. Sin fila: el grupo no accede al modelo. '
        'Ver [permisos de acceso](odoo.md#permisos-de-acceso).',
        _matriz_acceso(env),
        '## Parámetros del sistema',
        'Ajustes guardados en `ir.config_parameter` (ver [Operación](operacion.md#ajustes)).',
        _parametros(env),
    ]
    return '\n\n'.join(secciones) + '\n'


def escribir(env):
    """Regenera docs/referencia.md.

    @param env Entorno de Odoo con el módulo instalado.
    @return Path del archivo escrito.
    """
    ARCHIVO.write_text(generar(env), encoding='utf-8')
    return ARCHIVO


def _celda(texto):
    """Texto apto para una celda de tabla Markdown (una línea, `|` escapado).

    @param texto Texto o valor cualquiera.
    @return Texto limpio.
    """
    return ' '.join(str(texto or '').split()).replace('|', '\\|')


def _campos_propios(modelo):
    """Campos que define o modifica este módulo en un modelo (sin columnas automáticas).

    @param modelo Modelo (recordset vacío).
    @return Lista de campos ordenada por nombre.
    """
    return [campo for nombre, campo in sorted(modelo._fields.items())
            if MODULO in campo._modules and nombre not in models.MAGIC_COLUMNS]


def _diagrama(modelos):
    """Diagrama entidad-relación Mermaid de los campos relacionales propios.

    @param modelos Modelos a incluir.
    @return Bloque Markdown con el diagrama.
    """
    def nodo(nombre):
        """Identificador Mermaid de un modelo: 'sale.order' → 'sale_order'.

        @param nombre Nombre técnico del modelo.
        @return Identificador.
        """
        return nombre.replace('.', '_')

    lineas = ['```mermaid', 'erDiagram']
    for modelo in modelos:
        for campo in _campos_propios(modelo):
            if campo.related or campo.type not in ('many2one', 'many2many'):
                continue
            if campo.type == 'many2one':
                relacion = '}o--||' if campo.required else '}o--o|'
            else:
                relacion = '}o--o{'
            lineas.append(f'    {nodo(modelo._name)} {relacion} {nodo(campo.comodel_name)} : {campo.name}')
    lineas.append('```')
    return '\n'.join(lineas)


def _detalle(campo):
    """Columna "Detalle" de un campo: destino, valores, obligatoriedad, cálculo y ayuda.

    @param campo Campo del ORM.
    @return Texto de la celda.
    """
    detalle = []
    if campo.type in RELACIONALES:
        detalle.append(f'→ `{campo.comodel_name}`')
    if campo.type == 'selection' and isinstance(campo.selection, list):
        detalle.append('valores: ' + ', '.join(f'`{clave}`' for clave, _etiqueta in campo.selection))
    if campo.required:
        detalle.append('obligatorio')
    if campo.related:
        ruta = campo.related if isinstance(campo.related, str) else '.'.join(campo.related)
        detalle.append(f"related `{ruta}`")
    elif campo.compute:
        detalle.append('calculado' + (' (guardado)' if campo.store else ''))
    if campo.config_parameter if hasattr(campo, 'config_parameter') else False:
        detalle.append(f'parámetro `{campo.config_parameter}`')
    if campo.help:
        detalle.append(campo.help)
    return _celda('; '.join(detalle))


def _tabla_campos(modelo):
    """Tabla de campos propios de un modelo.

    @param modelo Modelo (recordset vacío).
    @return Sección Markdown.
    """
    tipo = ' (asistente)' if modelo._transient else ' (servicio RPC)' if modelo._abstract else ''
    filas = [f'| `{c.name}` | {c.type} | {_celda(c.string)} | {_detalle(c)} |' for c in _campos_propios(modelo)]
    cabecera = f'### `{modelo._name}` — {_celda(modelo._description)}{tipo}'
    if not filas:
        return cabecera + '\n\nSin campos propios.'
    return '\n'.join([cabecera, '', '| Campo | Tipo | Etiqueta | Detalle |', '|---|---|---|---|', *filas])


def _metodos_publicos(modelo):
    """Métodos públicos que este módulo define en un modelo, con la primera línea de su docstring.

    @param modelo Modelo (recordset vacío).
    @return dict {nombre: resumen}.
    """
    metodos = {}
    for clase in type(modelo).__mro__:
        if not clase.__module__.startswith(f'odoo.addons.{MODULO}.'):
            continue
        for nombre, valor in vars(clase).items():
            if inspect.isfunction(valor) and not nombre.startswith('_') and not hasattr(models.BaseModel, nombre):
                metodos.setdefault(nombre, (inspect.getdoc(valor) or '').split('\n')[0])
    return metodos


def _llamadores(env):
    """Quién llama a cada método: botones de vistas del módulo y `orm.call` del JavaScript.

    @param env Entorno de Odoo.
    @return dict {(modelo, método): set de descripciones}.
    """
    llamadores = {}
    datos = env['ir.model.data'].search([('module', '=', MODULO), ('model', '=', 'ir.ui.view')])
    for vista in env['ir.ui.view'].browse(datos.mapped('res_id')).exists():
        for boton in etree.fromstring(vista.arch_db).iter('button'):
            if boton.get('type') == 'object':
                modelo = vista.model
                for ancestro in reversed(list(boton.iterancestors('field'))):
                    campo = env[modelo]._fields.get(ancestro.get('name'))
                    modelo = campo.comodel_name if campo is not None and campo.comodel_name else modelo
                llamadores.setdefault((modelo, boton.get('name')), set()).add(f'botón en `{vista.name}`')
    for js in _archivos(('static/src',), '*.js'):
        for modelo, metodo in JS_ORM_CALL.findall(js.read_text(encoding='utf-8')):
            llamadores.setdefault((modelo, metodo), set()).add(f'JS `{js.relative_to(RAIZ)}`')
    return llamadores


def _llamadas_codigo(metodo):
    """Archivos del módulo que llaman a un método por nombre: Python (fuera de tests/) y
    plantillas QWeb de vistas y reportes.

    @param metodo Nombre del método.
    @return set de descripciones de los archivos.
    """
    patron = re.compile(rf'\.{metodo}\(')
    archivos = _archivos(('models', 'controllers'), '*.py') + _archivos(('views', 'report'), '*.xml')
    return {f"{'QWeb ' if archivo.suffix == '.xml' else ''}`{archivo.relative_to(RAIZ)}`" for archivo in archivos
            if patron.search(archivo.read_text(encoding='utf-8'))}


def _puntos_de_entrada(env, modelos):
    """Tabla de métodos públicos y sus llamadores.

    @param env Entorno de Odoo.
    @param modelos Modelos a incluir.
    @return Tabla Markdown.
    """
    llamadores = _llamadores(env)
    filas = []
    for modelo in modelos:
        for metodo, doc in sorted(_metodos_publicos(modelo).items()):
            origenes = sorted(llamadores.get((modelo._name, metodo), set()) | _llamadas_codigo(metodo))
            filas.append(f'| `{modelo._name}` | `{metodo}` | {_celda(doc)} | {_celda("; ".join(origenes)) or "—"} |')
    return '\n'.join(['| Modelo | Método | Qué hace | Llamado desde |', '|---|---|---|---|', *filas])


def _matriz_acceso(env):
    """Tabla de permisos de acceso (`ir.model.access`) del módulo.

    @param env Entorno de Odoo.
    @return Tabla Markdown.
    """
    datos = env['ir.model.data'].search([('module', '=', MODULO), ('model', '=', 'ir.model.access')])
    accesos = env['ir.model.access'].browse(datos.mapped('res_id')).exists()
    filas = []
    for acceso in accesos.sorted(lambda a: (a.model_id.model, a.group_id.name or '')):
        permisos = ''.join(letra if permitido else '-' for letra, permitido in (
            ('L', acceso.perm_read), ('E', acceso.perm_write), ('C', acceso.perm_create), ('B', acceso.perm_unlink)))
        filas.append(f'| `{acceso.model_id.model}` | {_celda(acceso.group_id.name or "Todos")} | `{permisos}` |')
    return '\n'.join(['| Modelo | Grupo | Permisos |', '|---|---|---|', *filas])


def _parametros(env):
    """Tabla de los ajustes guardados como parámetros del sistema.

    @param env Entorno de Odoo.
    @return Tabla Markdown.
    """
    filas = []
    for campo in _campos_propios(env['res.config.settings']):
        parametro = getattr(campo, 'config_parameter', None)
        if parametro:
            filas.append(f'| `{parametro}` | {_celda(campo.string)} | {_celda(campo.default and campo.default(env["res.config.settings"]))} |')
    filas.append('| `cotizador.condiciones_generales_default` | Condiciones Generales Predeterminadas | '
                 'ver `DEFAULT_CONDICIONES_GENERALES` |')
    return '\n'.join(['| Parámetro | Ajuste | Por defecto |', '|---|---|---|', *sorted(filas)])
