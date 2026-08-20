# -*- coding: utf-8 -*-
import json
import logging
import re
import urllib.request
import urllib.error
import ssl

_logger = logging.getLogger(__name__)

BCRA_API_BASE_URL = "https://api.bcra.gob.ar/centraldedeudores/v1.0"

SITUACION_LABELS = {
    1: "1 - Situación Normal",
    2: "2 - Con Seguimiento Especial",
    3: "3 - Con Problemas",
    4: "4 - Alto Riesgo de Insolvencia",
    5: "5 - Irrecuperable",
    6: "6 - Irrecuperable por Disposición Técnica",
}


def sanitize_cuit(cuit_raw):
    """Limpia el CUIT eliminando caracteres no numéricos y valida que tenga 11 dígitos."""
    if not cuit_raw:
        return None
    cleaned = re.sub(r'\D', '', str(cuit_raw).strip())
    if len(cleaned) == 11:
        return cleaned
    return None


def _fetch_json(url, timeout=8):
    """Realiza una petición GET segura a la API del BCRA retornando el JSON deserializado."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            if resp.status == 200:
                raw_data = resp.read().decode('utf-8')
                return json.loads(raw_data)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # 404 significa que no hay registros / sin deuda
            _logger.info("BCRA API 404 (Sin deuda o no encontrado) para URL: %s", url)
            return {"status": 404, "results": None}
        _logger.warning("BCRA API HTTPError %s en URL %s: %s", e.code, url, e.reason)
        return {"status": e.code, "error": str(e.reason)}
    except Exception as e:
        _logger.warning("Error de conexión con API BCRA (%s): %s", url, e)
        return {"status": 500, "error": str(e)}
    return None


def consultar_bcra_completo(cuit_raw):
    """
    Consulta la situación de deudas financieras y cheques rechazados en la Central de Deudores del BCRA.
    
    Retorna un diccionario estructurado:
    {
        'success': bool,
        'cuit': str,
        'denominacion': str,
        'tiene_deuda': bool,
        'peor_situacion': str ('1'..'6' o False),
        'monto_total_deuda': float, # En pesos
        'deudas': list of dicts,
        'cheques_rechazados': list of dicts,
        'mensaje_resumen': str,
    }
    """
    cuit = sanitize_cuit(cuit_raw)
    if not cuit:
        return {
            'success': False,
            'error': "CUIT inválido o incompleto (se requieren 11 dígitos).",
            'tiene_deuda': False,
            'deudas': [],
            'cheques_rechazados': [],
        }

    # 1. Consulta de Deudas
    deudas_url = f"{BCRA_API_BASE_URL}/Deudas/{cuit}"
    deudas_res = _fetch_json(deudas_url)

    denominacion = ""
    deudas_list = []
    peor_sit_num = 0
    total_deuda_pesos = 0.0

    if deudas_res and deudas_res.get('status') == 200 and deudas_res.get('results'):
        results = deudas_res['results']
        denominacion = results.get('denominacion', '')
        periodos = results.get('periodos', [])
        
        # Procesamos el último período reportado
        if periodos:
            ultimo_periodo = periodos[0]
            periodo_cod = ultimo_periodo.get('periodo', '')
            # Formatear periodo YYYYMM -> MM/YYYY
            if len(periodo_cod) == 6:
                periodo_str = f"{periodo_cod[4:6]}/{periodo_cod[:4]}"
            else:
                periodo_str = periodo_cod

            for ent in ultimo_periodo.get('entidades', []):
                sit = ent.get('situacion', 1)
                # Monto viene en miles de pesos en la API del BCRA
                monto_miles = float(ent.get('monto', 0.0) or 0.0)
                monto_pesos = monto_miles * 1000.0
                total_deuda_pesos += monto_pesos

                if sit > peor_sit_num:
                    peor_sit_num = sit

                obs_items = []
                if ent.get('refinanciaciones'):
                    obs_items.append("Refinanciaciones")
                if ent.get('recategorizacionOblig'):
                    obs_items.append("Recategorización Obligatoria")
                if ent.get('situacionJuridica'):
                    obs_items.append("Situación Jurídica")
                if ent.get('procesoJud'):
                    obs_items.append("Proceso Judicial")
                if ent.get('enRevision'):
                    obs_items.append("En Revisión")
                if ent.get('irrecDisposicionTecnica'):
                    obs_items.append("Irrecuperable Técnica")

                deudas_list.append({
                    'periodo': periodo_str,
                    'entidad': ent.get('entidad', 'Entidad No Especificada'),
                    'situacion': str(sit),
                    'situacion_desc': SITUACION_LABELS.get(sit, f"Situación {sit}"),
                    'monto': monto_pesos,
                    'dias_atraso': int(ent.get('diasAtrasoPago', 0) or 0),
                    'observaciones': ", ".join(obs_items) if obs_items else "Sin observaciones",
                })

    # 2. Consulta de Cheques Rechazados
    cheques_url = f"{BCRA_API_BASE_URL}/Deudas/ChequesRechazados/{cuit}"
    cheques_res = _fetch_json(cheques_url)
    cheques_list = []

    if cheques_res and cheques_res.get('status') == 200 and cheques_res.get('results'):
        ch_results = cheques_res['results']
        if not denominacion:
            denominacion = ch_results.get('denominacion', '')
        for ch in ch_results.get('chequesRechazados', []):
            monto_ch = float(ch.get('monto', 0.0) or 0.0)
            cheques_list.append({
                'nro_cheque': str(ch.get('nroCheque', '-')),
                'fecha_rechazo': ch.get('fechaRechazo', False),
                'monto': monto_ch,
                'causal': ch.get('causal', 'Sin Causal'),
                'estado': "Pagado" if ch.get('pagado') else ("Levantado" if ch.get('levantado') else "Pendiente / Impago"),
            })

    tiene_deuda = (len(deudas_list) > 0 and total_deuda_pesos > 0) or len(cheques_list) > 0
    peor_sit_str = str(peor_sit_num) if peor_sit_num > 0 else ("1" if deudas_list else False)

    # Construir mensaje de resumen
    if tiene_deuda:
        deuda_fmt = f"{total_deuda_pesos:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        sit_lbl = SITUACION_LABELS.get(peor_sit_num, f"Situación {peor_sit_num}")
        mensaje = f"El cliente registra una deuda total de $ {deuda_fmt} ({sit_lbl})"
        if cheques_list:
            mensaje += f" y {len(cheques_list)} cheque(s) rechazado(s)."
        else:
            mensaje += "."
    else:
        mensaje = "Sin deudas financieras ni cheques rechazados informados en la Central de Deudores del BCRA."

    return {
        'success': True,
        'cuit': cuit,
        'denominacion': denominacion,
        'tiene_deuda': tiene_deuda,
        'peor_situacion': peor_sit_str,
        'monto_total_deuda': total_deuda_pesos,
        'deudas': deudas_list,
        'cheques_rechazados': cheques_list,
        'mensaje_resumen': mensaje,
    }
