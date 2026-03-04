# Feature Workflow Plugin for OpenCode

## Quick Start

### Commands (use Ctrl+P to access)
- **feature-status** - Show dashboard
- **feature-capture** - Add feature to backlog
- **feature-plan** - Start implementing
- **feature-ship** - Complete feature

### Agents (use @mention)
- @project-manager - Requirements analysis
- @security-reviewer - Security audit
- @qa-engineer - QA validation
- @system-designer - Architecture
- @api-designer - API design
- @frontend-architect - Frontend design
- And more...

### Skills (loaded automatically)
All skills in the `skills/` directory are available via the skill tool.

## How It Works

1. **Create idea.md** → Feature added to backlog
2. **Create plan.md** → Feature moves to in-progress
3. **Create shipped.md** → Feature completed

The plugin auto-generates DASHBOARD.md and manages session titles.

## File Structure

```
docs/features/
├── DASHBOARD.md              # Auto-generated
├── my-feature/
│   ├── idea.md               # Backlog
│   ├── plan.md               # In-progress
│   └── shipped.md            # Completed
```
