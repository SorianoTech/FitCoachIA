import httpx
import asyncio
import base64

class SecureLLMAdapter:
    def __init__(
        self,
        base_url: str = "http://fitcoach-llm:11555",
        username: str = "fitcoach_bot",
        password: str = "TU_CONTRASEÑA_SEGURA"
    ):
        self.base_url = base_url
        
        # Crear header de Basic Auth (si lo necesitas con Nginx)
        #credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        credentials = "svPHnE8O6k5xG9mFoaM9tgjjbM3lRJjK"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {credentials}",
            "User-Agent": "FitCoachIA-Bot/1.0"
        }
        self.client = httpx.AsyncClient(
            timeout=320,
            headers=self.headers
        )
    
    async def chat(
        self,
        messages: list,
        model: str = "phi-2.Q4_K_M.gguf",
        temperature: float = 0.7,
        max_tokens: int = 256
    ) -> str:
        """Llamar endpoint /v1/chat/completions (OpenAI-compatible)"""
        try:
            response = await self.client.post(
                f"{self.base_url}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
            )
            response.raise_for_status()
            
            # Extraer el contenido de la respuesta
            data = response.json()
            return data.get("choices", [])[0].get("message", {}).get("content", "").strip()
            #return data["choices"][0]["message"]["content"].strip()
        
        except httpx.HTTPStatusError as e:
            print(f"Error LLM: {e.status_code} - {e.response.text}")
            raise

# Test
async def test():
    llm = SecureLLMAdapter(
        #base_url="http://fitcoach-llm:11434",  # Sin Basic Auth si solo tienes Nginx
        base_url="http://localhost:11555",  # Usar localhost desde el host
        # username="fitcoach_bot",
        # password="tu_contraseña"
    )
    
    messages = [
        {
            "role": "system",
            "content": "You are a fitness coach interviewing someone about their fitness goals. Be encouraging and ask follow-up questions."
        },
        {
            "role": "user",
            "content": "I want to start exercising but I don't know where to begin"
        }
    ]
    
    response = await llm.chat(
        messages=messages,
        temperature=0.7,
        max_tokens=150
    )
    
    print("Coach response:")
    print(response)

if __name__ == "__main__":
    asyncio.run(test())