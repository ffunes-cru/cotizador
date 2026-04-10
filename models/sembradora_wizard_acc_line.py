from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)

class SembradoraConfigWizardLine(models.TransientModel):
    _name = 'sembradora.config.wizard.line'
    
    wizard_id = fields.Many2one('sembradora.config.wizard')
    attribute_id = fields.Many2one('product.attribute', string='Atributo')
    value_id = fields.Many2one('product.attribute.value', string='Valor')
    value_domain_ids = fields.Many2many('product.attribute.value', compute='_compute_value_domain')

    @api.depends('attribute_id', 'wizard_id.line_ids.value_id')
    def _compute_value_domain(self):
        for record in self:
            # Si es la primera línea, solo filtramos por atributo
            # Si hay líneas previas, filtramos por la matriz
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