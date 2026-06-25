## Imported Claude Cowork project instructions

# Summoners War Team Optimizer - Project Specification

## Project Overview

Build a fully functional desktop application for Summoners War that performs team-based optimization rather than single-monster optimization.

Existing tools such as SWOP are excellent at optimizing individual monsters but struggle with optimizing entire dungeon teams simultaneously. The goal of this project is to create a next-generation optimizer focused on complete team optimization, dungeon success rates, and account progression analysis.

I already have an existing codebase that will serve as the starting point for this project. The application should improve and expand upon the existing implementation rather than starting from scratch whenever possible.

---

# Core Requirements

## 1. JSON Import System

### Supported Input

* Summoners War Exporter (SWEX) JSON files
* Multiple account profiles
* Automatic validation of imported data

### Import Data

The system must import:

* Monsters
* Monster stats
* Skills
* Runes
* Rune upgrades
* Grindstones
* Enchant gems
* Artifacts
* Buildings
* Guild bonuses
* Summoner level bonuses
* Arena towers
* Account progression information

The application should maintain an internal database representation of all imported account data.

---

# 2. Rune Optimization Engine

Create a modern optimization engine capable of:

### Monster Optimization

* Stat targeting
* Effective HP targeting
* Speed tuning
* Accuracy requirements
* Resistance requirements
* Damage requirements

### Constraints

Allow users to define:

* Minimum speed
* Minimum HP
* Minimum DEF
* Minimum Accuracy
* Minimum Resistance
* Minimum Crit Rate
* Minimum Crit Damage
* Minimum Attack

### Rune Logic

Optimizer must consider:

* Rune sets
* Broken sets
* Grind values
* Gem values
* Innate stats
* Efficiency calculations
* Actual in-game stat calculations

### Performance

Optimization should support:

* Multi-threading
* Large rune inventories
* Fast search algorithms
* Caching of calculations

---

# 3. Team-Based Optimization (Highest Priority Feature)

This is the primary differentiator from existing tools.

The optimizer must optimize entire teams simultaneously rather than optimizing monsters independently.

## Supported Content

### Dungeons

* Giants Abyss Hard
* Dragons Abyss Hard
* Necropolis Abyss Hard
* Spiritual Realm
* Steel Fortress
* Punisher's Crypt

### Arena

* Arena Offense
* Arena Defense

### Guild Content

* Siege Offense
* Siege Defense
* Guild War Offense
* Guild War Defense

### World Arena

* Draft analysis
* Speed contest calculations

---

# Team Optimization Requirements

The optimizer must:

* Allocate runes across all team members
* Prevent rune conflicts
* Optimize total team performance
* Optimize turn order
* Optimize speed tuning
* Optimize damage output
* Optimize survivability

Example:

If Monster A requires the fastest Swift set, the optimizer must automatically adjust all remaining monsters around that decision.

The system must never optimize monsters independently and then combine them afterward.

---

# 4. Dungeon Damage Calculator

Build a complete damage calculation engine.

The calculator must support:

* Skill multipliers
* Attack scaling
* Defense scaling
* HP scaling
* Crit damage
* Artifacts
* Skill-ups
* Buildings
* Guild bonuses
* Leader skills
* Buffs
* Debuffs

### Wave Analysis

The system should calculate:

* Damage against waves
* Damage against bosses
* Required damage thresholds
* One-shot potential

### Optimization Goals

Examples:

* Can this Julie clear Wave 1?
* Can this Teshar clear Wave 2?
* Does this team have enough damage for a speed run?
* What is the minimum stat requirement for a successful run?

---

# 5. Artifact Optimization

Support full artifact optimization.

Include:

* Artifact efficiency
* Damage increase calculations
* Skill-specific bonuses
* Element bonuses
* Additional damage effects

The optimizer should determine the best artifact combination for a monster or team.

---

# 6. Rune and Artifact Inventory Analyzer

Create an account progression analysis system.

## Rune Quality Analysis

Determine:

* Average efficiency
* Set quality
* Slot quality
* Rune depth
* Grind quality

### Example Output

Swift Set:

* Average speed roll quality
* Average efficiency
* Top 10%
* Bottom 10%

Violent Set:

* Average speed roll quality
* Average efficiency
* Top 10%
* Bottom 10%

---

# Sell Recommendations

The application should identify:

* Low-value runes
* Duplicate runes
* Inefficient runes
* Obsolete runes

Example:

"Your account's average Swift rune speed is 16."

Recommended keep threshold:

* Swift: 16+ speed
* Violent: 15+ speed
* Will: 14+ speed

Any rune below the threshold should be flagged for review.

---

# 7. Account Progression Analytics

The system should answer:

* What is the current strength of my account?
* Which dungeon should I focus on?
* Which rune set is weakest?
* Which monsters should receive upgrades first?
* Which runes are limiting my progression?

Generate actionable recommendations.

---

# 8. Technology Requirements

Preferred Stack:

Frontend:

* PySide6

Backend:

* Python

Database:

* SQLite

Performance:

* NumPy
* Pandas
* Numba (optional)

Optimization:

* OR-Tools
* Genetic Algorithms
* Constraint Solvers

---

# Development Phases

Phase 1:

* JSON Import
* Database Layer
* Rune Inventory Viewer

Phase 2:

* Monster Rune Optimizer

Phase 3:

* Team-Based Optimizer

Phase 4:

* Damage Calculator

Phase 5:

* Dungeon Team Builder

Phase 6:

* Account Analytics

Phase 7:

* Advanced Optimization and AI Suggestions

---

# Final Goal

Create the most powerful desktop-based Summoners War optimization tool available, with team-level optimization as the primary feature and account progression analysis as the secondary feature.
