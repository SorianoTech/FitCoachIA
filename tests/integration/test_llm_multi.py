from test_llm import SecureLLMAdapter
import asyncio


async def interview_conversation():
    llm = SecureLLMAdapter(base_url="http://localhost:11555")
    
    # Contexto del entrevistador
    system_prompt = """You are an expert fitness coach conducting an interview.
Your role is to:
1. Ask one question at a time about the person's fitness goals
2. Listen to their response and ask follow-up questions
3. Be encouraging and supportive
4. Identify their fitness level and preferences
Keep responses concise (2-3 sentences max)."""
    
    # Historial de mensajes (lo mantiene la app)
    conversation = [
        {"role": "system", "content": system_prompt}
    ]
    
    # Primera pregunta del coach
    user_input = "I want to get fit but don't know where to start"
    
    conversation.append({"role": "user", "content": user_input})
    
    # Obtener respuesta del coach
    coach_response = await llm.chat(
        messages=conversation,
        temperature=0.7,
        max_tokens=100
    )
    
    print(f"Coach: {coach_response}")
    
    # Añadir respuesta al historial
    conversation.append({
        "role": "assistant",
        "content": coach_response
    })
    
    # Segunda pregunta del usuario
    user_input_2 = "I'm 35 years old and mostly sedentary"
    
    conversation.append({"role": "user", "content": user_input_2})
    
    # Siguiente respuesta
    response_2 = await llm.chat(
        messages=conversation,
        temperature=0.7,
        max_tokens=100
    )
    
    print(f"Coach: {response_2}")

asyncio.run(interview_conversation())