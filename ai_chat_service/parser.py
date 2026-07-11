import re
from typing import Generator, Tuple

class StreamTutorParser:
    """
    Parses live JSON chunks from Gemini, detecting the emotion and 
    yielding completed Chinese clauses/sentences as soon as they appear.
    """
    def __init__(self):
        self.buffer = ""
        self.emotion = "neutral"
        self.in_chinese_content = False
        self.escaped = False
        self.found_emotion = False
        self.current_clause = ""
        self.delimiters = {'。', '！', '？', '.', '!', '?'}

    def feed(self, chunk: str) -> Generator[Tuple[str, str], None, None]:
        """Feeds a new chunk of the JSON stream and yields completed sentences/clauses."""
        self.buffer += chunk
        
        # 1. Attempt to find emotion if we haven't found it yet
        if not self.found_emotion:
            match = re.search(r'"emotion"\s*:\s*"([^"]+)"', self.buffer)
            if match:
                self.emotion = match.group(1)
                self.found_emotion = True
                
        # 2. Attempt to find the start of target_text
        if not self.in_chinese_content:
            match = re.search(r'"target_text"\s*:\s*"', self.buffer)
            if match:
                self.buffer = self.buffer[match.end():]
                self.in_chinese_content = True
                self.escaped = False
                self.current_clause = ""
                
        # 3. If we are in the target_text block, parse characters
        if self.in_chinese_content:
            chars_processed = 0
            for i, char in enumerate(self.buffer):
                if self.escaped:
                    self.current_clause += char
                    self.escaped = False
                    chars_processed = i + 1
                    continue
                if char == '\\':
                    self.escaped = True
                    chars_processed = i + 1
                    continue
                if char == '"':
                    # End of target_text
                    self.in_chinese_content = False
                    self.buffer = self.buffer[i + 1:]
                    sentence = self.current_clause.strip()
                    if sentence:
                        yield sentence, self.emotion
                    self.current_clause = ""
                    return
                
                self.current_clause += char
                chars_processed = i + 1
                
                # If we hit a punctuation, yield the clause/sentence
                if char in self.delimiters:
                    sentence = self.current_clause.strip()
                    if sentence:
                        yield sentence, self.emotion
                    self.current_clause = ""
                    
            self.buffer = self.buffer[chars_processed:]
