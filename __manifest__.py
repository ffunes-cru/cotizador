# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Cotizador",
    "version": '19.0.1.0.0',
    "author": "Franco Funes",
    "depends": [
        'base',
        'base_import_module',
        'sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/config_view.xml',
        'views/plan_pago_views.xml',
    ],
    'installable': True,
}
