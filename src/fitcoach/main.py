from fastapi import FastAPI

app = FastAPI(title="FitCoach IA - API de Prueba")

@app.get("/")
async def root():
    return {
        "message": "¡FitCoach IA está funcionando!",
        "status": "online",
        "version": "0.1.0"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
