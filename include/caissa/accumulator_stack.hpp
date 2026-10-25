#pragma once
#include "caissa/network.hpp"
namespace caissa {
struct AccumulatorWork {
    std::uint64_t pushes=0,materializations=0,perspective_copies=0;
    std::uint64_t perspective_refreshes=0,delta_squares=0;
    AccumulatorWork& operator+=(const AccumulatorWork& other);
};
// One stack belongs to one search worker and one immutable network. Frames
// retain piece changes even when a node never needs a neural evaluation.
class AccumulatorStack {
public:
    explicit AccumulatorStack(const Network& network,bool lazy):network_(network),lazy_(lazy){}
    void reset(const Position& position);
    void push(const Position& after,const Undo& before);
    void pop() noexcept;
    const Accumulator& get(const Position& position);
    const AccumulatorWork& work()const noexcept{return work_;}
    std::size_t depth()const noexcept{return depth_;}
private:
    struct Change {Square square;Piece before,after;};
    struct Frame {
        Accumulator accumulator;
        std::array<Change,4> changes{};
        std::uint8_t count=0;
        std::array<bool,2> ready{};
    };
    const Network& network_;
    bool lazy_,initialized_=false;
    std::array<Frame,max_ply> frames_{};
    std::size_t depth_=0;
    AccumulatorWork work_;
    void materialize(const Position& position,Color perspective);
};
}
