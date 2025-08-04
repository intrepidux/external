from . import models
from .hook import post_init_hook  # Importa el hook

def pre_init_hook(cr):
    # Lógica antes de la inicialización si es necesaria
    pass

def post_init_hook(cr, registry):
    # Llama al post_init_hook que has definido
    post_init_hook(cr, registry)