from openai import AsyncOpenAI, OpenAIError
from fastapi import HTTPException, status

from app.core.config import settings

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def summarize_with_openai(rendered_prompt: str) -> str:
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": rendered_prompt},
            ],
        )
        return response.choices[0].message.content
    except OpenAIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI API error: {str(e)}",
        )
