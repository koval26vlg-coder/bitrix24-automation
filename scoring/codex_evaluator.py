from __future__ import annotations
import asyncio
import json
import os
from typing import Any, Dict, Optional
from logging_setup import get_logger

logger = get_logger(__name__)

class CodexEvaluator:
    """
    Модуль интеграции с LLM (Gemini/Codex) для глубокого анализа звонков по критериям "Переговорщик".
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        # В реальной реализации здесь будет инициализация клиента Gemini или OpenAI
        self.api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")

    async def evaluate_transcript(self, transcript: str, deal_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполняет полный цикл оценки транскрипта.
        """
        if not transcript or len(transcript) < 50:
            return {
                "codex_error": "Транскрипт слишком короткий для анализа",
                "codex_overall_score": 0.0
            }

        logger.info(f"Запуск AI-анализа транскрипта (символов: {len(transcript)})")
        
        try:
            # Эмуляция вызова LLM
            await asyncio.sleep(1.5)
            
            # Пример структуры ответа, соответствующей критериям из kriterii_ocenki.txt
            result = {
                "codex_scores": {
                    "contact": 1.0,         # Поздоровался, представился, цель
                    "needs": 0.8,           # Вопросы, стратегия, активное слушание
                    "presentation": 0.7,    # Выгода, сравнение, примеры
                    "objections": 0.5,      # Спокойствие, причины, аргументы
                    "closing": 0.9          # Резюме, шаги, сроки
                },
                "codex_overall_score": 78.5,
                "codex_summary": "Менеджер уверенно ведет диалог, но требуется доработка в блоке аргументации цены.",
                "codex_pros": "Соблюдение регламента приветствия, проактивность в выявлении болей клиента.",
                "codex_cons": "Слабая работа с возражением «дорого», отсутствие четкого дедлайна по следующему шагу.",
                "codex_recommendations": "Использовать технику сэндвича при озвучивании стоимости. Назначить точное время звонка.",
                "codex_risk_level": "low"
            }
            
            logger.info(f"AI-анализ завершен. Оценка: {result['codex_overall_score']}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при AI-анализе: {e}")
            return {"codex_error": str(e), "codex_overall_score": 0.0}

    def _build_system_prompt(self) -> str:
        """
        Формирует промпт на основе формальных критериев (проект Переговорщик).
        """
        return """Ты — эксперт по контролю качества телефонных продаж. 
Твоя задача — проанализировать транскрипт и оценить работу менеджера по 5 блокам:
1. Установление контакта (приветствие, имя, цель).
2. Выявление потребностей (воронка вопросов, активное слушание).
3. Презентация (язык выгоды, экспертность, примеры).
4. Работа с возражениями (выяснение причин, отработка).
5. Закрытие (договоренности, сроки, прощание).

Формат ответа: JSON."""

    async def aclose(self):
        pass

async def main():
    evaluator = CodexEvaluator()
    sample = "Менеджер: Добрый день! Иван? Да. Удобно говорить? Да..."
    result = await evaluator.evaluate_transcript(sample, {"deal_id": "test"})
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
