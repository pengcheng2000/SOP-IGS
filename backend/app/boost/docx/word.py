from ...document_common.word import WordComError
from ...document_common.word import finalize_document as finalize_boost_with_word

if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(finalize_boost_with_word(Path(sys.argv[1])), ensure_ascii=False))

__all__ = ['WordComError', 'finalize_boost_with_word']
