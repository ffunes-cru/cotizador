from odoo import api, fields, models


class SembradoraAccessoryRule(models.Model):
    _name = 'sembradora.accessory.rule'
    _description = 'Regla de Exclusión/Inclusión de Accesorios'

    name = fields.Char(string='Nombre', required=True)

    rule_type = fields.Selection([
        ('exclusion', 'Exclusión'),
        ('inclusion', 'Inclusión'),
        ('choice', 'Opción única'),
    ], string='Tipo', required=True, default='exclusion',
        help='Exclusión (:e): como máximo un accesorio del grupo. '
             'Inclusión (:i / :it): los accesorios del grupo se habilitan solo cuando '
             'su accesorio habilitante (trigger) está seleccionado. '
             'Opción única (:u): siempre hay exactamente uno seleccionado; arranca el ESTANDAR '
             'y elegir una alternativa lo reemplaza.')

    description = fields.Text(
        string='Descripción',
        help='Descripción opcional del comportamiento de esta regla.')

    _name_type_unique = models.Constraint(
        'unique(name, rule_type)',
        'Ya existe una regla con este nombre y tipo.',
    )

    @api.depends('name', 'rule_type')
    def _compute_display_name(self):
        labels = dict(self._fields['rule_type'].selection)
        for rule in self:
            rule.display_name = f"{rule.name} ({labels.get(rule.rule_type, '')})"
