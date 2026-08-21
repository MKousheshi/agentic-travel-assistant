BOOKING_EXTRACTION_PROMPT = """
Extract only information explicitly stated by the user.

Never invent booking references, dates, date ranges, or monetary amounts.
If a required value is absent or ambiguous, return null for that field.
Do not infer a date from the current date unless the user explicitly asks
for a relative date and the application provides a trusted current datetime.

CURRENT DATE TIME: {0}
"""
