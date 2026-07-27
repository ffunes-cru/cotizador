from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class SembradoraAccessoryRule(models.Model):
    _name = 'sembradora.accessory.rule'
    _description = 'Regla de Exclusión/Inclusión de Accesorios'

    name = fields.Char(string='Nombre', required=True)

    rule_type = fields.Selection([
        ('exclusion', 'Exclusión'),
        ('inclusion', 'Inclusión'),
    ], string='Tipo', required=True, default='exclusion',
        help='Exclusión: solo se puede seleccionar un accesorio del grupo. '
             'Inclusión: los accesorios del grupo se habilitan solo cuando '
             'el accesorio trigger del grupo está seleccionado.')

    description = fields.Text(
        string='Descripción',
        help='Descripción opcional del comportamiento de esta regla.')

    _sql_constraints = [
        ('name_type_unique', 'unique(name, rule_type)',
         'Ya existe una regla con este nombre y tipo.'),
    ]

    @api.depends('name', 'rule_type')
    def _compute_display_name(self):
        for rule in self:
            tipo = "Inclusión" if rule.rule_type == 'inclusion' else "Exclusión"
            rule.display_name = f"{rule.name} ({tipo})"
