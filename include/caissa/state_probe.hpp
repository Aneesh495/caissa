#pragma once
#include "caissa/network.hpp"
#include <iosfwd>
namespace caissa {
// Bounded diagnostic transport over the same position and deferred neural
// state used in search. No saved pass flag stands in for an observed state.
int state_probe(std::istream& input,std::ostream& output,const Network& network);
}
