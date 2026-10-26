"""Day Trader: Jake Schincariol's MIT-licensed day-trader-skill 2.0.0 as an independent module.

The module runs the pinned upstream scripts themselves (not re-implementations) in an
offline, network-blocked, credential-free sandbox, normalises their outputs, and turns
validated trade plans into SideDeck research signals and proposals. It never places, approves
or records broker orders; execution can only ever pass through SideDeck's shared broker
gateway after separate owner release. Initial mode RESEARCH_ONLY; SIMULATION_ONLY for
offline acceptance.
"""
