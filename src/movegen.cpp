#include "caissa/position.hpp"
#include <algorithm>
#include <cmath>
namespace caissa {
bool Position::attacked(Square s, Color by, Bitboard occ) const {
    auto live=occupied(by)&occ;
    if(attacks::pawn(opposite(by),s)&pieces(by,Kind::pawn)&live) return true;
    if(attacks::knight(s)&pieces(by,Kind::knight)&live) return true;
    if(attacks::king(s)&pieces(by,Kind::king)&live) return true;
    if(attacks::bishop(s,occ)&(pieces(by,Kind::bishop)|pieces(by,Kind::queen))&live) return true;
    return (attacks::rook(s,occ)&(pieces(by,Kind::rook)|pieces(by,Kind::queen))&live)!=0;
}
Bitboard Position::checkers(Color c) const {
    auto s=king(c);auto enemy=opposite(c);auto occ=occupied();
    return (attacks::pawn(c,s)&pieces(enemy,Kind::pawn)) |
           (attacks::knight(s)&pieces(enemy,Kind::knight)) |
           (attacks::king(s)&pieces(enemy,Kind::king)) |
           (attacks::bishop(s,occ)&(pieces(enemy,Kind::bishop)|pieces(enemy,Kind::queen))) |
           (attacks::rook(s,occ)&(pieces(enemy,Kind::rook)|pieces(enemy,Kind::queen)));
}
Bitboard Position::pinned(Color c) const {
    Bitboard result=0,blockers=occupied(c)&~pieces(c,Kind::king);
    auto enemy=opposite(c);auto k=king(c);
    auto original=(attacks::bishop(k,occupied())&(pieces(enemy,Kind::bishop)|pieces(enemy,Kind::queen))) |
                  (attacks::rook(k,occupied())&(pieces(enemy,Kind::rook)|pieces(enemy,Kind::queen)));
    while(blockers) {
        auto s=pop_lsb(blockers);auto occ=occupied()&~bit(s);
        auto revealed=(attacks::bishop(k,occ)&(pieces(enemy,Kind::bishop)|pieces(enemy,Kind::queen))) |
                      (attacks::rook(k,occ)&(pieces(enemy,Kind::rook)|pieces(enemy,Kind::queen)));
        if(revealed&~original) result|=bit(s);
    }
    return result;
}
bool Position::can_castle(int wing) const {
    auto rook=rook_right(side_,wing);if(rook==no_square) return false;
    auto k=king(side_);int home=side_==Color::white?0:7;
    auto kt=square(wing?6:2,home), rt=square(wing?5:3,home);
    auto paths=attacks::segment(k,kt)|attacks::segment(rook,rt);
    if((occupied()&~bit(k)&~bit(rook))&paths) return false;
    auto king_path=attacks::segment(k,kt);
    auto transit_occupancy=occupied()&~bit(k);
    while(king_path) if(attacked(pop_lsb(king_path),opposite(side_),transit_occupancy)) return false;
    auto final_occupancy=(occupied()&~bit(k)&~bit(rook))|bit(rt)|bit(kt);
    return !attacked(kt,opposite(side_),final_occupancy);
}
Moves Position::pseudo_legal() const {
    Moves moves;moves.reserve(64);
    auto ours=occupied(side_), enemy=occupied(opposite(side_));
    auto forbidden=ours|pieces(opposite(side_),Kind::king);
    auto add_pawn=[&](Square from,Square to,MoveFlag flag) {
        if(rank(to)==0||rank(to)==7) for(Kind k:{Kind::queen,Kind::rook,Kind::bishop,Kind::knight}) moves.push_back({from,to,k,flag});
        else moves.push_back({from,to,Kind::none,flag});
    };
    auto pawns=pieces(side_,Kind::pawn);
    int step=side_==Color::white?8:-8, home=side_==Color::white?1:6;
    while(pawns) {
        auto s=pop_lsb(pawns);auto t=static_cast<Square>(static_cast<int>(s)+step);
        if(t<64&&!at(t)) {
            add_pawn(s,t,MoveFlag::normal);
            auto twice=static_cast<Square>(static_cast<int>(t)+step);
            if(rank(s)==home&&!at(twice)) moves.push_back({s,twice,Kind::none,MoveFlag::double_push});
        }
        auto targets=attacks::pawn(side_,s)&enemy&~pieces(opposite(side_),Kind::king);
        while(targets) add_pawn(s,pop_lsb(targets),MoveFlag::normal);
        if(ep_<64&&(attacks::pawn(side_,s)&bit(ep_))) moves.push_back({s,ep_,Kind::none,MoveFlag::en_passant});
    }
    for(Kind k:{Kind::knight,Kind::bishop,Kind::rook,Kind::queen,Kind::king}) {
        auto bb=pieces(side_,k);
        while(bb) {
            auto s=pop_lsb(bb);Bitboard targets=0;
            switch(k) {
                case Kind::knight: targets=attacks::knight(s);break;
                case Kind::bishop: targets=attacks::bishop(s,occupied());break;
                case Kind::rook: targets=attacks::rook(s,occupied());break;
                case Kind::queen: targets=attacks::queen(s,occupied());break;
                case Kind::king: targets=attacks::king(s);break;
                default: break;
            }
            targets&=~forbidden;
            while(targets) moves.push_back({s,pop_lsb(targets)});
        }
    }
    for(int wing=0;wing<2;++wing) if(can_castle(wing)) moves.push_back({king(side_),rook_right(side_,wing),Kind::none,MoveFlag::castle});
    return moves;
}
Moves Position::legal() {
    Moves out;auto all=pseudo_legal();out.reserve(all.size());auto us=side_;
    for(auto m:all) {
        auto undo=make(m);bool valid=!in_check(us);unmake(undo);
        if(valid) out.push_back(m);
    }
    return out;
}
Undo Position::save_state() const {
    Undo u;u.castling=castling_;u.ep=ep_;u.halfmove=halfmove_;u.fullmove=fullmove_;
    u.key=key_;u.history_size=history_.size();u.side=side_;return u;
}
void Position::save_square(Undo& u, Square s) {
    for(std::uint8_t i=0;i<u.count;++i) if(u.squares[i]==s) return;
    if(u.count>=4) throw std::logic_error("move touches more than four squares");
    u.squares[u.count]=s;u.pieces[u.count]=at(s);++u.count;
}
Undo Position::make(Move m) {
    if(!m.valid()||!at(m.from)||color(at(m.from))!=side_) throw InputError("invalid internal move");
    auto u=save_state();auto moving=at(m.from);auto captured=at(m.to);
    key_^=metadata_key();
    save_square(u,m.from);save_square(u,m.to);
    ep_=no_square;
    if(m.flag==MoveFlag::castle) {
        int wing=file(m.to)>file(m.from)?1:0;int home=rank(m.from);
        auto kt=square(wing?6:2,home),rt=square(wing?5:3,home);
        save_square(u,kt);save_square(u,rt);
        put(m.from,0);put(m.to,0);put(kt,moving);put(rt,piece(side_,Kind::rook));
        captured=0;
    } else {
        if(m.flag==MoveFlag::en_passant) {
            auto victim=static_cast<Square>(static_cast<int>(m.to)+(side_==Color::white?-8:8));
            save_square(u,victim);captured=at(victim);put(victim,0);
        }
        put(m.from,0);put(m.to,m.promotion==Kind::none?moving:piece(side_,m.promotion));
        if(m.flag==MoveFlag::double_push) ep_=static_cast<Square>((static_cast<int>(m.from)+m.to)/2);
    }
    for(Color c:{Color::white,Color::black}) for(int wing=0;wing<2;++wing) {
        auto& right=castling_[static_cast<std::size_t>(index(c))][static_cast<std::size_t>(wing)];
        if((c==side_&&kind(moving)==Kind::king)||right==m.from||right==m.to) right=no_square;
    }
    halfmove_=(captured||kind(moving)==Kind::pawn)?0:halfmove_+1;
    if(side_==Color::black) ++fullmove_;
    side_=opposite(side_);key_^=metadata_key();history_.push_back(repetition_key());
    return u;
}
Undo Position::make_null() {
    auto u=save_state();key_^=metadata_key();ep_=no_square;side_=opposite(side_);key_^=metadata_key();
    // Null moves are search artifacts and never enter game repetition history.
    return u;
}
void Position::unmake(const Undo& u) {
    for(std::uint8_t i=0;i<u.count;++i) put(u.squares[i],0);
    for(std::uint8_t i=0;i<u.count;++i) put(u.squares[i],u.pieces[i]);
    castling_=u.castling;ep_=u.ep;halfmove_=u.halfmove;fullmove_=u.fullmove;
    key_=u.key;side_=u.side;history_.resize(u.history_size);
}
std::string Position::uci(Move m) const {
    if(!m.valid()) return "0000";
    Square target=m.to;
    if(m.flag==MoveFlag::castle&&!chess960_) target=square(file(m.to)>file(m.from)?6:2,rank(m.from));
    auto s=square_name(m.from)+square_name(target);
    if(m.promotion!=Kind::none) s+=std::string_view(" pnbrqk")[static_cast<std::size_t>(m.promotion)];
    return s;
}
std::optional<Move> Position::parse_uci(std::string_view text) {
    if(text.size()<4||text.size()>5) return std::nullopt;
    for(auto m:legal()) if(uci(m)==text) return m;
    return std::nullopt;
}
int Position::repetitions() const {
    auto k=repetition_key();int n=0;
    auto count=std::min(history_.size(),static_cast<std::size_t>(halfmove_)+1);
    for(std::size_t i=history_.size()-count;i<history_.size();++i) if(history_[i]==k) ++n;
    return n;
}
std::uint64_t perft(Position& p,int depth) {
    if(depth<0||depth>12) throw InputError("perft depth must be in [0,12]");
    if(depth==0) return 1;
    auto moves=p.legal();if(depth==1) return moves.size();
    std::uint64_t count=0;
    for(auto m:moves) { auto u=p.make(m);count+=perft(p,depth-1);p.unmake(u); }
    return count;
}
std::vector<std::pair<std::string,std::uint64_t>> divide(Position& p,int depth) {
    if(depth<1||depth>12) throw InputError("divide depth must be in [1,12]");
    std::vector<std::pair<std::string,std::uint64_t>> rows;
    for(auto m:p.legal()) { auto text=p.uci(m);auto u=p.make(m);auto n=perft(p,depth-1);p.unmake(u);rows.emplace_back(text,n); }
    std::sort(rows.begin(),rows.end());return rows;
}
}
