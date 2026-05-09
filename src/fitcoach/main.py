from fastapi import FastAPI

from fitcoach.api.router import router

app = FastAPI(title="FitCoach IA - API de Prueba")
app.include_router(router)


@app.get("/")
async def root():
    return {
        "message": "¡FitCoach IA está funcionando!",
        "status": "online",
        "version": "0.1.0",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
