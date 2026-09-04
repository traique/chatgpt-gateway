from . import app as runtime
from . import openai_compat

openai_compat.install(runtime)
