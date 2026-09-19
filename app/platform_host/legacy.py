"""Legacy in-process composition for existing clients and fixture dependency overrides.
Production starts Core and product workers independently.
"""

from products.triad.api import router as product_router
from trading_core.api import *

app.include_router(product_router)
