from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class GameMemory:
    """Track important game events (WAY OUT WEST) for agent context."""
    
    # Key revelations
    revealed_secrets: Dict[str, str] = field(default_factory=dict)
    evidence_presented: List[str] = field(default_factory=list)
    accusations_made: List[tuple[str, str]] = field(default_factory=list)  # (accuser, accused)
    deals_proposed: List[str] = field(default_factory=list)
    deaths: List[str] = field(default_factory=list)
    
    # Important decisions
    judgment_result: str = ""
    
    def add_secret_revealed(self, character: str, secret: str):
        self.revealed_secrets[character] = secret
    
    def add_evidence(self, evidence: str):
        if evidence not in self.evidence_presented:
            self.evidence_presented.append(evidence)
    
    def add_accusation(self, accuser: str, accused: str):
        self.accusations_made.append((accuser, accused))
    
    def get_context_summary(self) -> str:
        """Generate a summary for agent context."""
        lines = ["📜 GAME MEMORY - IMPORTANT FACTS:"]
        
        if self.revealed_secrets:
            lines.append("\n🔓 REVEALED SECRETS:")
            for char, secret in self.revealed_secrets.items():
                lines.append(f"  - {char}: {secret}")
        
        if self.evidence_presented:
            lines.append("\n📋 EVIDENCE PRESENTED:")
            for evidence in self.evidence_presented:
                lines.append(f"  - {evidence}")
        
        if self.accusations_made:
            lines.append("\n⚖️ ACCUSATIONS:")
            for accuser, accused in self.accusations_made[-5:]:  # Last 5
                lines.append(f"  - {accuser} accused {accused}")
        
        if self.judgment_result:
            lines.append(f"\n⚖️ JUDGMENT: {self.judgment_result}")
        
        if self.deaths:
            lines.append(f"\n💀 DECEASED: {', '.join(self.deaths)}")
        
        return "\n".join(lines)