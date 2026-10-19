"""@file
Cliente de la API pública de la Central de Deudores del BCRA.

Funciones puras (sin ORM): las usan `sale.order` (alerta al elegir cliente y botón
*Situación BCRA*) y el asistente `cotizador.bcra.wizard`.

API: https://api.bcra.gob.ar/centraldedeudores/v1.0 — sin autenticación. Respuestas:
  - 200 con `{"status": 200, "results": {...}}`: hay registros para el CUIT.
  - 404: el CUIT no tiene registros (sin deuda informada).
  - otro código o error de red: **no se sabe** la situación; nunca se informa "sin deuda".
"""
import json
import logging
import re
import ssl
import urllib.error
import urllib.request

_logger = logging.getLogger(__name__)

## URL base de la API de la Central de Deudores.
BCRA_API_BASE_URL = "https://api.bcra.gob.ar/centraldedeudores/v1.0"

## Tiempo máximo de espera de cada consulta HTTP, en segundos.
BCRA_TIMEOUT = 8

## Descripción de cada situación crediticia (1 = normal … 6 = irrecuperable técnica).
SITUACION_LABELS = {
    1: "1 - Situación Normal",
    2: "2 - Con Seguimiento Especial",
    3: "3 - Con Problemas",
    4: "4 - Alto Riesgo de Insolvencia",
    5: "5 - Irrecuperable",
    6: "6 - Irrecuperable por Disposición Técnica",
}

## Marcas de cada deuda que se muestran como observaciones: (clave de la API, texto).
OBSERVACIONES = (
    ('refinanciaciones', "Refinanciaciones"),
    ('recategorizacionOblig', "Recategorización Obligatoria"),
    ('situacionJuridica', "Situación Jurídica"),
    ('procesoJud', "Proceso Judicial"),
    ('enRevision', "En Revisión"),
    ('irrecDisposicionTecnica', "Irrecuperable Técnica"),
)


class BcraError(Exception):
    """La API no respondió o respondió con error: la situación del CUIT es desconocida."""


def sanitize_cuit(cuit_raw):
    """Normaliza un CUIT a sus 11 dígitos.

    @param cuit_raw CUIT tal como está en el contacto (con o sin guiones), o vacío.
    @return Los 11 dígitos como texto, o `None` si no es un CUIT completo.
    """
    if not cuit_raw:
        return None
    cleaned = re.sub(r'\D', '', str(cuit_raw).strip())
    return cleaned if len(cleaned) == 11 else None


def format_pesos(amount):
    """Formatea un importe en pesos al estilo argentino: 1234567.5 → '1.234.567,50'.

    @param amount Importe.
    @return Texto con punto de miles y coma decimal.
    """
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fetch_results(url, timeout=BCRA_TIMEOUT):
    """Consulta un endpoint de la API con verificación TLS.

    @param url URL completa del endpoint.
    @param timeout Segundos máximos de espera.
    @return El objeto `results` de la respuesta, o `None` si la API responde 404 (sin registros).
    @throws BcraError Si hay error de red, de TLS, un código HTTP distinto de 200/404 o una
            respuesta que no es JSON.
    """
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8')).get('results')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        _logger.warning("BCRA API: HTTP %s en %s", e.code, url)
        raise BcraError(f"La API del BCRA respondió con error HTTP {e.code}.") from e
    except (OSError, ValueError) as e:  # red, TLS, timeout (OSError) o JSON inválido (ValueError)
        _logger.warning("BCRA API: error al consultar %s: %s", url, e)
        raise BcraError(f"No se pudo consultar la API del BCRA ({e}).") from e


def _parse_deudas(results):
    """Convierte las deudas del último período informado.

    @param results Objeto `results` del endpoint `/Deudas/{cuit}`, o `None`.
    @return Tupla `(denominacion, deudas, peor_situacion, total_pesos)` donde `deudas` es una
            lista de dicts con `periodo`, `entidad`, `situacion` (texto '1'…'6'),
            `situacion_desc`, `monto` (en pesos), `dias_atraso` y `observaciones`.
    """
    if not results:
        return '', [], 0, 0.0
    periodos = results.get('periodos') or []
    if not periodos:
        return results.get('denominacion', ''), [], 0, 0.0
    ultimo = periodos[0]  # la API ordena del más reciente al más antiguo
    codigo = ultimo.get('periodo', '')
    periodo = f"{codigo[4:6]}/{codigo[:4]}" if len(codigo) == 6 else codigo  # AAAAMM → MM/AAAA

    deudas, peor, total = [], 0, 0.0
    for ent in ultimo.get('entidades', []):
        situacion = ent.get('situacion', 1)
        monto = float(ent.get('monto', 0.0) or 0.0) * 1000.0  # la API informa miles de pesos
        total += monto
        peor = max(peor, situacion)
        observaciones = [texto for clave, texto in OBSERVACIONES if ent.get(clave)]
        deudas.append({
            'periodo': periodo,
            'entidad': ent.get('entidad', 'Entidad No Especificada'),
            'situacion': str(situacion),
            'situacion_desc': SITUACION_LABELS.get(situacion, f"Situación {situacion}"),
            'monto': monto,
            'dias_atraso': int(ent.get('diasAtrasoPago', 0) or 0),
            'observaciones': ", ".join(observaciones) or "Sin observaciones",
        })
    return results.get('denominacion', ''), deudas, peor, total


def _parse_cheques(results):
    """Convierte los cheques rechazados.

    @param results Objeto `results` del endpoint `/Deudas/ChequesRechazados/{cuit}`, o `None`.
    @return Tupla `(denominacion, cheques)` donde `cheques` es una lista de dicts con
            `nro_cheque`, `fecha_rechazo`, `monto`, `causal` y `estado`.
    """
    if not results:
        return '', []
    cheques = [{
        'nro_cheque': str(ch.get('nroCheque', '-')),
        'fecha_rechazo': ch.get('fechaRechazo', False),
        'monto': float(ch.get('monto', 0.0) or 0.0),
        'causal': ch.get('causal', 'Sin Causal'),
        'estado': "Pagado" if ch.get('pagado') else ("Levantado" if ch.get('levantado') else "Pendiente / Impago"),
    } for ch in results.get('chequesRechazados', [])]
    return results.get('denominacion', ''), cheques


def consultar_bcra_completo(cuit_raw):
    """Consulta deudas financieras y cheques rechazados de un CUIT.

    Si cualquiera de las dos consultas falla, devuelve `success = False`: un error de la API
    nunca se presenta como "sin deudas".

    @param cuit_raw CUIT del cliente (se normaliza con sanitize_cuit()).
    @return dict con:
      - `success` (bool) y, si es False, `error` (texto para el usuario);
      - `cuit`, `denominacion`;
      - `tiene_deuda` (bool): deuda financiera mayor a 0 o algún cheque rechazado;
      - `peor_situacion`: '1'…'6', o False sin deudas;
      - `monto_total_deuda`: total en pesos;
      - `deudas`, `cheques_rechazados`: listas (ver _parse_deudas() y _parse_cheques());
      - `mensaje_resumen`: texto de una línea.
    """
    vacio = {'success': False, 'tiene_deuda': False, 'deudas': [], 'cheques_rechazados': []}
    cuit = sanitize_cuit(cuit_raw)
    if not cuit:
        return {**vacio, 'error': "CUIT inválido o incompleto (se requieren 11 dígitos)."}
    try:
        deudas_res = _fetch_results(f"{BCRA_API_BASE_URL}/Deudas/{cuit}")
        cheques_res = _fetch_results(f"{BCRA_API_BASE_URL}/Deudas/ChequesRechazados/{cuit}")
    except BcraError as e:
        return {**vacio, 'cuit': cuit, 'error': str(e)}

    denominacion, deudas, peor, total = _parse_deudas(deudas_res)
    denominacion_ch, cheques = _parse_cheques(cheques_res)
    tiene_deuda = (bool(deudas) and total > 0) or bool(cheques)

    if tiene_deuda:
        mensaje = (f"El cliente registra una deuda total de $ {format_pesos(total)} "
                   f"({SITUACION_LABELS.get(peor, f'Situación {peor}')})")
        mensaje += f" y {len(cheques)} cheque(s) rechazado(s)." if cheques else "."
    else:
        mensaje = "Sin deudas financieras ni cheques rechazados informados en la Central de Deudores del BCRA."

    return {
        'success': True,
        'cuit': cuit,
        'denominacion': denominacion or denominacion_ch,
        'tiene_deuda': tiene_deuda,
        'peor_situacion': str(peor) if peor else ('1' if deudas else False),
        'monto_total_deuda': total,
        'deudas': deudas,
        'cheques_rechazados': cheques,
        'mensaje_resumen': mensaje,
    }
