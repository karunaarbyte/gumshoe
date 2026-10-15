import type { Problem, ProblemOption } from '../api/types';

/** The turn text a picker button sends: exactly the option's name. The agent parses it against
 * the accusation in progress. If the first real-backend run shows the agent needs a sentence
 * for `how` or `why`, this is the one line to change (see frontend/README.md). */
export function pickerText(option: ProblemOption, _axis: Problem['axis']): string {
  return option.name;
}
