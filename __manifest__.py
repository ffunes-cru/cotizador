# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Cotizador",
    "version": '19.0.1.0.0',
    "author": "Franco Funes",
    "depends": [
        'base',
        'base_import_module',
        'sale',
        'portal',
        'crm',
        'sale_crm',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/config_view.xml',
        'views/plan_pago_views.xml',
        'views/product_attribute_view.xml',
        'data/product_category_data.xml',
        'views/import_wizard_view.xml',
        'views/accessory_rule_view.xml',
        'views/res_config_settings_view.xml',
        'report/report_cotizacion_planes.xml',
        'views/portal_templates.xml',
        'views/price_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'cotizador/static/src/components/price_wizard/**/*',
        ],
    },
    'installable': True,
    'post_init_hook': '_post_init_hook',
}
