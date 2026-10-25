#include "caissa/accumulator_stack.hpp"
#include <cassert>
namespace caissa {
AccumulatorWork& AccumulatorWork::operator+=(const AccumulatorWork& other) {
    pushes+=other.pushes;materializations+=other.materializations;
    perspective_copies+=other.perspective_copies;
    perspective_refreshes+=other.perspective_refreshes;delta_squares+=other.delta_squares;
    return *this;
}
void AccumulatorStack::reset(const Position& p) {
    depth_=0;initialized_=true;auto& frame=frames_[0];frame.count=0;
    frame.ready={false,false};frame.accumulator.initialized=false;
    frame.accumulator.position_key=p.key();
    for(Color c:{Color::white,Color::black})
        frame.accumulator.buckets[static_cast<std::size_t>(index(c))]=king_bucket(c,p.king(c));
    if(!lazy_) {
        frame.accumulator=network_.refresh(p);frame.ready={true,true};
        ++work_.materializations;work_.perspective_refreshes+=2;
    }
}
void AccumulatorStack::push(const Position& after,const Undo& before) {
    if(!initialized_||frames_[depth_].accumulator.position_key!=before.key)
        throw std::logic_error("neural stack not owned by prior position");
    if(depth_+1>=frames_.size())throw std::logic_error("neural stack depth exceeded");
    if(before.count>4)throw std::logic_error("neural change count exceeded");
    auto& parent=frames_[depth_];auto& frame=frames_[depth_+1];
    frame.count=before.count;frame.ready={false,false};
    for(std::uint8_t i=0;i<before.count;++i) {
        auto s=before.squares[i];if(s>=64)throw std::logic_error("neural change square exceeded");
        frame.changes[i]={s,before.pieces[i],after.at(s)};
    }
    if(lazy_) {
        frame.accumulator.initialized=false;frame.accumulator.position_key=after.key();
        for(Color c:{Color::white,Color::black})
            frame.accumulator.buckets[static_cast<std::size_t>(index(c))]=king_bucket(c,after.king(c));
    } else {
        // Keep the established updater as a reference, including its exact
        // bucket-refresh behavior. Deferred frames never copy these values.
        frame.accumulator=parent.accumulator;work_.perspective_copies+=2;
        network_.update(after,before,frame.accumulator);frame.ready={true,true};
        for(std::size_t ci=0;ci<2;++ci) {
            if(frame.accumulator.buckets[ci]!=parent.accumulator.buckets[ci])++work_.perspective_refreshes;
            else work_.delta_squares+=before.count;
        }
        ++work_.materializations;
    }
    ++depth_;++work_.pushes;
}
void AccumulatorStack::pop() noexcept {
    assert(initialized_&&depth_>0);--depth_;
}
void AccumulatorStack::materialize(const Position& p,Color c) {
    auto ci=static_cast<std::size_t>(index(c));auto& current=frames_[depth_];
    if(current.ready[ci])return;
    auto bucket=current.accumulator.buckets[ci];std::size_t ancestor=depth_;
    while(ancestor>0) {
        --ancestor;
        if(frames_[ancestor].ready[ci]&&frames_[ancestor].accumulator.buckets[ci]==bucket)break;
    }
    auto& values=current.accumulator.values[ci];
    if(ancestor<depth_&&frames_[ancestor].ready[ci]&&frames_[ancestor].accumulator.buckets[ci]==bucket) {
        values=frames_[ancestor].accumulator.values[ci];++work_.perspective_copies;
        // The deltas telescope in the final king bucket, even if an unobserved
        // intermediate king left that bucket and returned. No intermediate
        // board, activation clipping or dense rounding participates here.
        for(std::size_t step=ancestor+1;step<=depth_;++step) {
            const auto& frame=frames_[step];
            for(std::uint8_t i=0;i<frame.count;++i) {
                auto change=frame.changes[i];if(change.before==change.after)continue;
                if(change.before)network_.add(values,feature_index(c,bucket,change.before,change.square),-1);
                if(change.after)network_.add(values,feature_index(c,bucket,change.after,change.square),1);
                ++work_.delta_squares;
            }
        }
    } else {
        values=network_.bias0_;
        for(Square s=0;s<64;++s)if(p.at(s))network_.add(values,feature_index(c,bucket,p.at(s),s),1);
        ++work_.perspective_refreshes;
    }
    current.ready[ci]=true;
}
const Accumulator& AccumulatorStack::get(const Position& p) {
    if(!initialized_||frames_[depth_].accumulator.position_key!=p.key())
        throw std::logic_error("stale neural stack position");
    auto& frame=frames_[depth_];
    if(!frame.accumulator.initialized) {
        materialize(p,Color::white);materialize(p,Color::black);
        frame.accumulator.initialized=true;++work_.materializations;
    }
    return frame.accumulator;
}
}
