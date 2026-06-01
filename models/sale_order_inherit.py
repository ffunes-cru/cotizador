from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class SaleOrderInherit(models.Model):
    _inherit = 'sale.order'

    # # Relación con planes de pago
    # plan_pago_ids = fields.One2many(
    #     'cotizador.plan.pago',
    #     'sale_order_id',
    #     string='Planes de Pago')

    # has_plan_pago = fields.Boolean(default=False)
    # has_cheques = fields.Boolean(compute='_compute_plan_types')
    # has_documentos = fields.Boolean(compute='_compute_plan_types')
    # has_credito_bancario = fields.Boolean(compute='_compute_plan_types')

    # @api.depends('plan_pago_ids.tipo')
    # def _compute_plan_types(self):
    #     for order in self:
    #         tipos = order.plan_pago_ids.mapped('tipo')
    #         order.has_canje_cereal = 'canje_cereal' in tipos
    #         order.has_cheques = 'cheques' in tipos
    #         order.has_documentos = 'documentos' in tipos
    #         order.has_credito_bancario = 'credito_bancario' in tipos

    def action_open_config_wizard(self):
        """Abre nuestro wizard de configuración de sembradora en lugar del configurador de Odoo."""
        _logger.info("=== HILO DE EJECUCIÓN: action_open_config_wizard en sale.order ===")
        _logger.info("Contexto recibido de Odoo: %s", self.env.context)
        _logger.info("self (sale.order recordset): %s (ID: %s)", self, self.id)

        order_id = self.id or self.env.context.get('active_id') or self.env.context.get('params', {}).get('id')
        _logger.info("ID de Orden resuelto para el wizard: %s", order_id)

        # Si el ID obtenido no es un entero real, es una cotización virtual en edición (no guardada aún)
        if order_id and not isinstance(order_id, int):
            _logger.info("Advertencia: El ID detectado es de tipo virtual/NewId (no guardado aún): %s", order_id)

        action = {
            'type': 'ir.actions.act_window',
            'name': 'Configurar Sembradora',
            'res_model': 'sembradora.config.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_sale_order_id': order_id},
        }
        _logger.info("Acción de ventana devuelta por Python: %s", action)
        return action

    # def action_open_plan_pago_wizard(self):
    #     """Abre el wizard para seleccionar/ver planes de pago."""
    #     _logger.info("=== HILO DE EJECUCIÓN: action_open_plan_pago_wizard en sale.order ===")
    #     order_id = self.id or self.env.context.get('active_id') or self.env.context.get('params', {}).get('id')
    #     _logger.info("ID de Orden resuelto para Planes de Pago: %s", order_id)

    #     return {
    #         'type': 'ir.actions.act_window',
    #         'name': 'Planes de Pago',
    #         'res_model': 'cotizador.plan.pago.wizard',
    #         'view_mode': 'form',
    #         'target': 'new',
    #         'context': {'default_sale_order_id': order_id},
    #     }
    
    def action_open_plan_pago_wizard(self):
        self.ensure_one()
        
        # Buscamos las plantillas reales
        templates = self.env['cotizador.plan.pago.template.line'].search([
            ('template_id.active', '=', True)
        ])
        
        # Preparamos las líneas del wizard
        lines = []
        for t in templates:
            lines.append((0, 0, {
                'template_line_id': t.id,
                'tipo': t.tipo,
                'name': t.name,
                'descuento': t.descuento,
            }))
        
        # CREACIÓN FÍSICA: Al crearlo aquí, Odoo le da IDs reales en la BD y el botón de la fila no fallará
        wizard = self.env['cotizador.plan.pago.wizard'].create({
            'sale_order_id': self.id,
            'wizard_line_ids': lines,
        })
        
        # Retornamos la acción para abrir el registro que ya existe
        return {
            'name': 'Seleccionar Plan de Pago',
            'type': 'ir.actions.act_window',
            'res_model': 'cotizador.plan.pago.wizard',
            'res_id': wizard.id, # <--- Apunta al ID real recién creado
            'view_mode': 'form',
            'target': 'new',
        }

class SaleOrderLineInherit(models.Model):
    _inherit = 'sale.order.line'

    is_plan_pago = fields.Boolean(default=False)

    def action_open_config_wizard(self):
        """Delegación del botón del listado de líneas al sale.order padre."""
        _logger.info("=== HILO DE EJECUCIÓN: action_open_config_wizard en sale.order.line (Delegación) ===")
        _logger.info("Contexto recibido de Odoo: %s", self.env.context)
        _logger.info("self (sale.order.line recordset): %s", self)

        order_id = False
        if self.order_id:
            order_id = self.order_id
            _logger.info("ID de Orden obtenido directamente desde la línea (self.order_id): %s", order_id)
        else:
            # Buscar en el contexto por todos los medios posibles
            ctx = self.env.context
            parent_id = (
                ctx.get('default_sale_order_id') or
                ctx.get('active_id') or 
                ctx.get('default_order_id') or 
                ctx.get('params', {}).get('id')
            )
            _logger.info("Intento de recuperación del Parent ID de la cotización: default_sale_order_id=%s, active_id=%s, default_order_id=%s, params.id=%s",
                         ctx.get('default_sale_order_id'), ctx.get('active_id'), ctx.get('default_order_id'), ctx.get('params', {}).get('id'))
            _logger.info("Parent ID resuelto: %s", parent_id)
            if parent_id:
                order_id = self.env['sale.order'].browse(parent_id)

        if not order_id:
            _logger.error("ERROR CRÍTICO: No se pudo identificar la orden de venta activa desde el contexto.")
            raise ValidationError("No se pudo identificar la orden de venta activa. Por favor, guarde la cotización antes de configurar.")

        _logger.info("Delegando llamada a sale.order (ID: %s)", order_id.id)
        return order_id.action_open_config_wizard()
