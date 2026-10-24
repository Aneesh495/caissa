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
Bitboard Position::attackers_to(Square s,Color by) const {
    return (attacks::pawn(opposite(by),s)&pieces(by,Kind::pawn)) |
           (attacks::knight(s)&pieces(by,Kind::knight)) |
           (attacks::king(s)&pieces(by,Kind::king)) |
           (attacks::bishop(s,occupied())&(pieces(by,Kind::bishop)|pieces(by,Kind::queen))) |
           (attacks::rook(s,occupied())&(pieces(by,Kind::rook)|pieces(by,Kind::queen)));
}
Bitboard Position::checkers(Color c) const {return attackers_to(king(c),opposite(c));}
Bitboard Position::pinned(Color c) const {
    Bitboard result=0;auto enemy=opposite(c);auto k=king(c);
    auto transparent=occupied()&~occupied(c);
    auto candidates=(attacks::bishop(k,transparent)&(pieces(enemy,Kind::bishop)|pieces(enemy,Kind::queen))) |
                    (attacks::rook(k,transparent)&(pieces(enemy,Kind::rook)|pieces(enemy,Kind::queen)));
    while(candidates) {
        auto attacker=pop_lsb(candidates);auto blockers=attacks::between(k,attacker)&occupied();
        if(std::popcount(blockers)==1&&(blockers&occupied(c)))result|=blockers;
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
namespace {
enum class Generation {all,tactical};
// Returning true from the consumer stops enumeration. Full collection, tactical
// collection and availability share one stable pseudo-move order.
template<class Consumer>
bool enumerate(const Position& p,Generation generation,Consumer&& consume) {
    auto us=p.side(),them=opposite(us);auto enemy=p.occupied(them);
    auto forbidden=p.occupied(us)|p.pieces(them,Kind::king);
    auto pawn=[&](Square from,Square to,MoveFlag flag) {
        if(rank(to)==0||rank(to)==7) {
            for(Kind k:{Kind::queen,Kind::rook,Kind::bishop,Kind::knight})
                if(consume(Move{from,to,k,flag}))return true;
            return false;
        }
        return consume(Move{from,to,Kind::none,flag});
    };
    auto pawns=p.pieces(us,Kind::pawn);int step=us==Color::white?8:-8,home=us==Color::white?1:6;
    while(pawns) {
        auto from=pop_lsb(pawns);auto to=static_cast<Square>(static_cast<int>(from)+step);
        if(to<64&&!p.at(to)) {
            bool promotion=rank(to)==0||rank(to)==7;
            if((generation==Generation::all||promotion)&&pawn(from,to,MoveFlag::normal))return true;
            if(generation==Generation::all&&rank(from)==home) {
                auto twice=static_cast<Square>(static_cast<int>(to)+step);
                if(!p.at(twice)&&consume(Move{from,twice,Kind::none,MoveFlag::double_push}))return true;
            }
        }
        auto targets=attacks::pawn(us,from)&enemy&~p.pieces(them,Kind::king);
        while(targets)if(pawn(from,pop_lsb(targets),MoveFlag::normal))return true;
        if(p.ep()<64&&(attacks::pawn(us,from)&bit(p.ep()))&&consume(Move{from,p.ep(),Kind::none,MoveFlag::en_passant}))return true;
    }
    for(Kind kind:{Kind::knight,Kind::bishop,Kind::rook,Kind::queen,Kind::king}) {
        auto pieces=p.pieces(us,kind);
        while(pieces) {
            auto from=pop_lsb(pieces);Bitboard targets=0;
            switch(kind) {
                case Kind::knight:targets=attacks::knight(from);break;
                case Kind::bishop:targets=attacks::bishop(from,p.occupied());break;
                case Kind::rook:targets=attacks::rook(from,p.occupied());break;
                case Kind::queen:targets=attacks::queen(from,p.occupied());break;
                case Kind::king:targets=attacks::king(from);break;
                default:break;
            }
            targets&=~forbidden;
            if(generation==Generation::tactical)targets&=enemy;
            while(targets)if(consume(Move{from,pop_lsb(targets)}))return true;
        }
    }
    if(generation==Generation::all)for(int wing=0;wing<2;++wing)
        if(p.can_castle(wing)&&consume(Move{p.king(us),p.rook_right(us,wing),Kind::none,MoveFlag::castle}))return true;
    return false;
}
struct Legality {
    Color us;Square king;int checks;Bitboard pins,evasion;
    explicit Legality(const Position& p):us(p.side()),king(p.king(us)) {
        auto attackers=p.checkers(us);checks=std::popcount(attackers);pins=p.pinned(us);evasion=~Bitboard{0};
        if(checks==1){auto from=static_cast<Square>(std::countr_zero(attackers));evasion=attacks::between(king,from)|bit(from);}
    }
    bool allows(Position& p,Move m) const {
        if(m.flag==MoveFlag::castle)return true;
        if(m.flag==MoveFlag::en_passant) {
            auto undo=p.make(m);bool legal=!p.in_check(us);p.unmake(undo);return legal;
        }
        if(m.from==king) {
            auto occupancy=(p.occupied()&~bit(king))|bit(m.to);
            return !p.attacked(m.to,opposite(us),occupancy);
        }
        if(checks>=2||!(evasion&bit(m.to)))return false;
        if(pins&bit(m.from)) {
            int ax=file(m.from)-file(king),ay=rank(m.from)-rank(king);
            int bx=file(m.to)-file(king),by=rank(m.to)-rank(king);
            if(ax*by!=ay*bx)return false;
        }
        return true;
    }
};
}
Moves Position::pseudo_legal() const {
    Moves moves;moves.reserve(64);
    enumerate(*this,Generation::all,[&](Move m){moves.push_back(m);return false;});return moves;
}
Moves Position::legal() {
    Legality legality(*this);Moves moves;moves.reserve(64);
    enumerate(*this,Generation::all,[&](Move m){if(legality.allows(*this,m))moves.push_back(m);return false;});return moves;
}
Moves Position::legal_tactical() {
    Legality legality(*this);Moves moves;moves.reserve(16);
    enumerate(*this,Generation::tactical,[&](Move m){if(legality.allows(*this,m))moves.push_back(m);return false;});return moves;
}
MoveAvailability Position::availability() {
    Legality legality(*this);
    bool any=enumerate(*this,Generation::all,[&](Move m){return legality.allows(*this,m);});
    return MoveAvailability(key_,legality.checks>0,any);
}
Undo Position::save_state() const {
    Undo u;u.castling=castling_;u.ep=ep_;u.halfmove=halfmove_;u.fullmove=fullmove_;
    u.key=key_;u.history_size=history_.size();u.side=side_;u.synthetic_depth=synthetic_depth_;return u;
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
    auto u=save_state();++synthetic_depth_;key_^=metadata_key();ep_=no_square;side_=opposite(side_);key_^=metadata_key();
    // Null moves are search artifacts and never enter game repetition history.
    return u;
}
void Position::unmake(const Undo& u) {
    for(std::uint8_t i=0;i<u.count;++i) put(u.squares[i],0);
    for(std::uint8_t i=0;i<u.count;++i) put(u.squares[i],u.pieces[i]);
    castling_=u.castling;ep_=u.ep;halfmove_=u.halfmove;fullmove_=u.fullmove;
    key_=u.key;side_=u.side;synthetic_depth_=u.synthetic_depth;history_.resize(u.history_size);
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
