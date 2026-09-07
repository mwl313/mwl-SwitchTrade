"""P1 harness facade: real native observer/Netplay beneath the P0 menu scenario.

Only this test facade uses a thread to adapt the async product API to the P0
fixture. It owns no frontend process and isn't used by the product CLI.
"""
import asyncio
import queue
import threading

from switchtrade.endpoints.retroarch_gpsp.netplay import LocalNetplay
from switchtrade.endpoints.retroarch_gpsp.process import ProcessObserver
from stock_reference import StockNetplayLaunch


class ProductionProbe(StockNetplayLaunch):
    def open(self, *, process):
        self.listener.close()
        observer = ProcessObserver.select(process.pid)
        connection = ProbeConnection(observer, self.port)
        try:
            connection.open()
            return connection
        except BaseException:
            connection.close()
            raise


class ProbeConnection:
    def __init__(self, observer, port):
        self.loop = asyncio.new_event_loop()
        self.session = LocalNetplay(observer, port, handshake_timeout=20)
        self.queue = queue.Queue(256)
        self.thread = threading.Thread(target=self.loop.run_forever, name="gpsp-p1-probe")
        self.thread.start()
        self.reader = None
        self.result = None

    def call(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout=25)

    @property
    def error(self):
        return self.session.failure

    def open(self):
        async def open_and_read():
            await self.session.open(asyncio.Event())
            await self.session.barrier()
            async def pump():
                while True:
                    self.queue.put_nowait(await self.session.receive())
            self.reader = asyncio.create_task(pump())
        self.call(open_and_read())

    def receive(self, timeout):
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def send(self, payload):
        self.call(self.session.send(payload))

    def barrier(self):
        self.call(self.session.barrier())

    def close(self):
        if self.result is not None:
            return self.result
        async def stop():
            report = await self.session.close()
            if self.reader is not None:
                self.reader.cancel()
                await asyncio.gather(self.reader, return_exceptions=True)
            return report.endpoint_stopped and report.local_resources_released and report.transport_drained
        try:
            self.result = self.call(stop())
        except Exception:
            self.result = False
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)
            if not self.thread.is_alive():
                self.loop.close()
            else:
                self.result = False
        return self.result
