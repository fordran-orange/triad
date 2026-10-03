FROM python@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock && rm /tmp/requirements.lock
COPY infrastructure/product-tests.lock /tmp/product-tests.lock
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
RUN pip install --no-cache-dir -r /tmp/product-tests.lock && python -m playwright install --with-deps chromium && rm /tmp/product-tests.lock
COPY app/trading_core/__init__.py app/trading_core/work.py app/trading_core/product_sdk.py app/trading_core/market.py /opt/core/app/trading_core/
COPY app/trading_core/research/__init__.py app/trading_core/research/contracts.py app/trading_core/research/calendar.py app/trading_core/research/data.py app/trading_core/research/engine.py app/trading_core/research/planning.py /opt/core/app/trading_core/research/
ENV PYTHONPATH=/workspace/app:/opt/core/app
