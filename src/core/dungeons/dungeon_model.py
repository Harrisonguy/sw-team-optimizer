from __future__ import annotations

from pydantic import BaseModel, Field


class DungeonEnemy(BaseModel):
    enemy_id: int | None = None
    monster_id: int | None = None

    stars: int | None = None
    level: int | None = None

    hp: int = 0
    attack: int = 0
    defense: int = 0
    speed: int = 0

    resistance: int = 0
    crit_rate_bonus: int = 0
    crit_damage_reduction: int = 0
    accuracy_bonus: int = 0

    @property
    def ehp_score(self) -> int:
        """
        Simple rough target toughness score.
        We can refine later with the real SW damage formula.
        """
        return self.hp + (self.defense * 10)


class DungeonWave(BaseModel):
    wave_number: int
    enemies: list[DungeonEnemy] = Field(default_factory=list)

    @property
    def enemy_count(self) -> int:
        return len(self.enemies)

    @property
    def max_speed(self) -> int:
        return max((enemy.speed for enemy in self.enemies), default=0)

    @property
    def max_resistance(self) -> int:
        return max((enemy.resistance for enemy in self.enemies), default=0)

    @property
    def max_accuracy_bonus(self) -> int:
        return max((enemy.accuracy_bonus for enemy in self.enemies), default=0)

    @property
    def highest_hp_enemy(self) -> DungeonEnemy | None:
        if not self.enemies:
            return None

        return max(self.enemies, key=lambda enemy: enemy.hp)

    @property
    def highest_defense_enemy(self) -> DungeonEnemy | None:
        if not self.enemies:
            return None

        return max(self.enemies, key=lambda enemy: enemy.defense)

    @property
    def toughest_enemy(self) -> DungeonEnemy | None:
        if not self.enemies:
            return None

        return max(self.enemies, key=lambda enemy: enemy.ehp_score)


class DungeonLevelProfile(BaseModel):
    level_id: int
    dungeon_id: int

    dungeon_name: str
    dungeon_slug: str

    floor: int | None = None
    difficulty: str | None = None

    energy_cost: int | None = None
    total_slots: int | None = None

    waves: list[DungeonWave] = Field(default_factory=list)

    @property
    def display_name(self) -> str:
        if self.difficulty:
            return f"{self.dungeon_name} {self.difficulty}"

        if "abyss" in self.dungeon_slug and self.floor == 1:
            return f"{self.dungeon_name} Normal"

        if "abyss" in self.dungeon_slug and self.floor == 2:
            return f"{self.dungeon_name} Hard"

        if self.floor is not None:
            return f"{self.dungeon_name} B{self.floor}"

        return self.dungeon_name

    @property
    def wave_count(self) -> int:
        return len(self.waves)

    @property
    def max_enemy_speed(self) -> int:
        return max((wave.max_speed for wave in self.waves), default=0)

    @property
    def max_enemy_resistance(self) -> int:
        return max((wave.max_resistance for wave in self.waves), default=0)

    @property
    def max_accuracy_bonus(self) -> int:
        return max((wave.max_accuracy_bonus for wave in self.waves), default=0)

    @property
    def boss_wave(self) -> DungeonWave | None:
        if not self.waves:
            return None

        return self.waves[-1]

    @property
    def wave_clear_waves(self) -> list[DungeonWave]:
        """
        For Cairos dungeons, wave 1 and wave 3 are usually the trash waves.
        This is what Julie/Lushen/Teshar wave-clear checks usually care about.
        """
        return [
            wave
            for wave in self.waves
            if wave.wave_number in {1, 3}
        ]

    @property
    def midboss_wave(self) -> DungeonWave | None:
        for wave in self.waves:
            if wave.wave_number == 2:
                return wave

        return None

    def get_wave(self, wave_number: int) -> DungeonWave | None:
        for wave in self.waves:
            if wave.wave_number == wave_number:
                return wave

        return None


class DungeonSummary(BaseModel):
    dungeon_id: int
    name: str
    slug: str
    category: str | None = None
    icon: str | None = None
    level_ids: list[int] = Field(default_factory=list)

class ManualDungeonOverride(BaseModel):
    key: str
    display_name: str
    source: str = "manual"

    dungeon_slug: str
    floor: int | None = None
    level_id: int | None = None

    notes: str | None = None

    max_enemy_speed: int = 0
    max_enemy_resistance: int = 0

    wave_clear_targets: list[DungeonEnemy] = Field(default_factory=list)
    boss_targets: list[DungeonEnemy] = Field(default_factory=list)