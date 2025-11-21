# -*- coding: utf-8 -*-
# from odoo import http


# class L10nDoSequenceInherit(http.Controller):
#     @http.route('/l10n_do_sequence_inherit/l10n_do_sequence_inherit/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/l10n_do_sequence_inherit/l10n_do_sequence_inherit/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('l10n_do_sequence_inherit.listing', {
#             'root': '/l10n_do_sequence_inherit/l10n_do_sequence_inherit',
#             'objects': http.request.env['l10n_do_sequence_inherit.l10n_do_sequence_inherit'].search([]),
#         })

#     @http.route('/l10n_do_sequence_inherit/l10n_do_sequence_inherit/objects/<model("l10n_do_sequence_inherit.l10n_do_sequence_inherit"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('l10n_do_sequence_inherit.object', {
#             'object': obj
#         })
