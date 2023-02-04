#pragma once
#include <iosfwd>
namespace caissa {
// Bounded diagnostics of the real search and transposition table. No network,
// alternate move generator, external evaluator or test search is substituted.
int search_probe(std::istream& input,std::ostream& output);
}
