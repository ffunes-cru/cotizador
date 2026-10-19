"""@file
Reglas entre accesorios de una configuración (exclusión, inclusión y opción única)."""
from odoo import api, fields, models


class SembradoraAccessoryRule(models.Model):
    """Regla (`sembradora.accessory.rule`): agrupa líneas de accesorio con un comportamiento.

    Una regla no guarda sus miembros: cada `sembradora.config.accessory.line` la referencia en
    `rule_ids`, así la misma regla se reutiliza en todas las configuraciones.

    | Tipo | Sufijo CSV | Regla |
    |---|---|---|
    | `exclusion` | `:e` / `:et` | Como máximo un accesorio elegido del grupo. |
    | `inclusion` | `:i` / `:it` | Los miembros se habilitan solo si está elegido el habilitante (`is_trigger`, sufijo `:it`). |
    | `choice` | `:u` | Exactamente uno elegido; arranca el ESTANDAR. |

    La coherencia de un conjunto de reglas la valida sembradora_config.validate_rule_set().
    """
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

    ## Nombre único por tipo: el importador identifica las reglas por (tipo, nombre).
    _name_type_unique = models.Constraint(
        'unique(name, rule_type)',
        'Ya existe una regla con este nombre y tipo.',
    )

    @api.depends('name', 'rule_type')
    def _compute_display_name(self):
        """Nombre visible: "Nombre (Tipo)", p. ej. "Cuchillas (Exclusión)"."""
        labels = dict(self._fields['rule_type'].selection)
        for rule in self:
            rule.display_name = f"{rule.name} ({labels.get(rule.rule_type, '')})"
