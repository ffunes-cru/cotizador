"""@file
Hook de MkDocs (mkdocs.yml): en el sitio, los enlaces de docs/*.md a archivos del módulo
(`../models/x.py#L12`) apuntan al archivo en GitHub, en la rama actual. En GitHub y en el editor
esos enlaces relativos ya funcionan; en el sitio no existen los archivos de código.
"""
import re
import subprocess

## Enlace Markdown relativo a un archivo de código del módulo: `](../carpeta/archivo.ext#Lnn)`.
ENLACE_CODIGO = re.compile(r'\]\(\.\./((?:models|controllers|tools|static|tests|scripts|views|report|data|security)/[^)#\s]+)(#L\d+)?\)')


def _rama():
    """Rama de git actual del módulo, para que los enlaces abran el código de esa rama.

    @return Nombre de la rama, o 'main' si no se puede saber.
    """
    try:
        return subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True,
                              text=True, check=True).stdout.strip() or 'main'
    except (OSError, subprocess.CalledProcessError):
        return 'main'


def on_page_markdown(markdown, page, config, files):
    """Reescribe los enlaces a archivos de código como enlaces a GitHub.

    @param markdown Texto Markdown de la página.
    @param page Página de MkDocs (no se usa).
    @param config Configuración de MkDocs; usa `repo_url`.
    @param files Archivos del sitio (no se usa).
    @return Markdown con los enlaces reescritos.
    """
    base = f"{config['repo_url'].rstrip('/')}/blob/{_rama()}"
    return ENLACE_CODIGO.sub(lambda m: f"]({base}/{m[1]}{m[2] or ''})", markdown)
