from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)

class SembradoraConfigWizardLine(models.TransientModel):
    _name = 'sembradora.config.wizard.line'
    _description = 'Línea de Configuración de Sembradora'
    
    wizard_id = fields.Many2one('sembradora.config.wizard')
    attribute_id = fields.Many2one('product.attribute', string='Atributo')
    value_id = fields.Many2one('product.attribute.value', string='Valor')
    value_domain_ids = fields.Many2many('product.attribute.value', compute='_compute_value_domain')

    # Indica si esta línea fue auto-seleccionada por tener una sola opción disponible
    # Se muestra en readonly/grisado en la vista
    is_single_option = fields.Boolean(string='Opción Única', default=False)

    # Propagado desde product.attribute: controla si el atributo se muestra en la descripción
    show_in_description = fields.Boolean(
        related='attribute_id.show_in_description',
        string='Mostrar en Descripción',
        readonly=True)

    # Si es opción única Y no se muestra en descripción → ocultar la fila completa en el wizard
    is_hidden = fields.Boolean(
        string='Ocultar Línea',
        compute='_compute_is_hidden',
        store=True)

    @api.depends('is_single_option', 'show_in_description')
    def _compute_is_hidden(self):
        for record in self:
            record.is_hidden = record.is_single_option and not record.show_in_description

    @api.depends('attribute_id', 'wizard_id.line_ids.value_id')
    def _compute_value_domain(self):
        for record in self:
            if not record.wizard_id.modelo_id or not record.attribute_id:
                record.value_domain_ids = self.env['product.attribute.value']
                continue

            # Construir dominio completo de una sola vez
            domain = [('modelo_id', '=', record.wizard_id.modelo_id.id)]
            
            # Miramos qué eligieron los hermanos ARRIBA de esta línea
            otras_lineas = record.wizard_id.line_ids.filtered(
                lambda l: l.attribute_id != record.attribute_id and l.value_id
            )
            
            for line in otras_lineas:
                domain.append(('value_ids', 'in', line.value_id.id))
            
            configs = self.env['sembradora.config.rel'].search(domain)
            valores = configs.mapped('value_ids').filtered(lambda v: v.attribute_id == record.attribute_id)
            record.value_domain_ids = valores