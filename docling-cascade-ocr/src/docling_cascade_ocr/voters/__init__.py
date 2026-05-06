from .base import BaseVoter, VoterUnavailable, build_voters
from .tesseract_voter import TesseractVoter, TesseractTsvVoter
from .ocrmypdf_voter import OcrmypdfVoter
from .paddleocr_voter import PaddleOcrVoter
from .doctr_voter import DoctrVoter
from .easyocr_voter import EasyOcrVoter
from .pix2struct_voter import Pix2StructVoter
from .docling_default_voter import DoclingDefaultVoter

__all__ = [
    "BaseVoter",
    "VoterUnavailable",
    "build_voters",
    "TesseractVoter",
    "TesseractTsvVoter",
    "OcrmypdfVoter",
    "PaddleOcrVoter",
    "DoctrVoter",
    "EasyOcrVoter",
    "Pix2StructVoter",
    "DoclingDefaultVoter",
]
