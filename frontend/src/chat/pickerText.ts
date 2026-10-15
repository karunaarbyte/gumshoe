import type { Problem, ProblemOption } from '../api/types';

/** The turn text a picker button sends. The first real-backend run showed the agent rejects a
 * bare option name for `how` (low-confidence clarify) and accepts a sentence, so how and why are
 * sent as `I think it was <name>`. The who axis still sends the bare name (not yet verified live). */
export function pickerText(option: ProblemOption, axis: Problem['axis']): string {
  return axis === 'how' || axis === 'why' ? `I think it was ${option.name}` : option.name;
}
