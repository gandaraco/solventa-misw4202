# locust/locustfile.py
import random

from locust import HttpUser, between, task


class ClienteCotizacion(HttpUser):
    wait_time = between(0.05, 0.2)

    @task
    def cotizar(self):
        self.client.post(
            "/cotizacion",
            json={
                "cliente": "carga-%d" % random.randint(1, 100000),
                "producto": "auto",
                "valor_asegurado": random.choice([20000, 50000, 80000, 120000]),
            },
            name="POST /cotizacion",
        )
