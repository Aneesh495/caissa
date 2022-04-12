#include "caissa/reference.hpp"
#include <algorithm>
#include <cmath>
namespace caissa::reference {
namespace {
struct Mailbox {
    std::array<int,120> cells{};
    int turn=1;
    int ep=0;
    std::array<std::array<int,2>,2> rooks{};
    explicit Mailbox(const Position& p) {
        cells.fill(99);
        for(int r=0;r<8;++r) for(int f=0;f<8;++f) {
            auto pc=p.at(square(f,r));cells[static_cast<std::size_t>(21+r*10+f)]=pc?(color(pc)==Color::white?1:-1)*static_cast<int>(kind(pc)):0;
        }
        turn=p.side()==Color::white?1:-1;ep=p.ep()<64?convert(p.ep()):0;
        for(Color c:{Color::white,Color::black}) for(int w=0;w<2;++w) {
            auto s=p.rook_right(c,w);rooks[static_cast<std::size_t>(index(c))][static_cast<std::size_t>(w)]=s<64?convert(s):0;
        }
    }
    static int convert(Square s) { return 21+rank(s)*10+file(s); }
    static Square convert(int s) { return square((s-21)%10,(s-21)/10); }
    int operator[](int i) const { return cells[static_cast<std::size_t>(i)]; }
    int king(int side) const {
        for(int s=21;s<=98;++s) if((*this)[s]==side*6) return s;
        throw std::logic_error("reference king absent");
    }
    bool threatened(int target,int enemy) const {
        for(int s=21;s<=98;++s) {
            int p=(*this)[s];if(p==99||p*enemy<=0) continue;
            int k=std::abs(p),dx=(target%10)-(s%10),dy=(target/10)-(s/10);
            if(k==1&&dy==enemy&&std::abs(dx)==1) return true;
            if(k==2&&std::abs(dx)*std::abs(dy)==2) return true;
            if(k==6&&std::max(std::abs(dx),std::abs(dy))==1) return true;
            bool diagonal=std::abs(dx)==std::abs(dy)&&dx!=0;
            bool straight=(dx==0)!=(dy==0);
            if(!((k==3&&diagonal)||(k==4&&straight)||(k==5&&(diagonal||straight)))) continue;
            int step=((dy>0)-(dy<0))*10+(dx>0)-(dx<0);
            bool clear=true;for(int t=s+step;t!=target;t+=step) if((*this)[t]!=0) {clear=false;break;}
            if(clear) return true;
        }
        return false;
    }
    bool castle(int wing) const {
        int r=rooks[turn==1?0:1][static_cast<std::size_t>(wing)];if(!r) return false;
        int k=king(turn),home=turn==1?20:90,kt=home+(wing?7:3),rt=home+(wing?6:4);
        for(auto [a,b]:{std::pair{k,kt},std::pair{r,rt}})
            for(int s=std::min(a,b);s<=std::max(a,b);++s) if(s!=k&&s!=r&&(*this)[s]) return false;
        Mailbox transit=*this;transit.cells[static_cast<std::size_t>(k)]=0;
        for(int s=std::min(k,kt);s<=std::max(k,kt);++s) if(transit.threatened(s,-turn)) return false;
        transit.cells[static_cast<std::size_t>(r)]=0;transit.cells[static_cast<std::size_t>(rt)]=turn*4;
        return !transit.threatened(kt,-turn);
    }
    Mailbox apply(Move m) const {
        Mailbox next=*this;int a=convert(m.from),b=convert(m.to),p=(*this)[a];
        next.cells[static_cast<std::size_t>(a)]=0;
        if(m.flag==MoveFlag::castle) {
            int home=turn==1?20:90;bool right=b>a;
            next.cells[static_cast<std::size_t>(b)]=0;
            next.cells[static_cast<std::size_t>(home+(right?7:3))]=turn*6;
            next.cells[static_cast<std::size_t>(home+(right?6:4))]=turn*4;
        } else {
            if(m.flag==MoveFlag::en_passant) next.cells[static_cast<std::size_t>(b-turn*10)]=0;
            next.cells[static_cast<std::size_t>(b)]=m.promotion==Kind::none?p:turn*static_cast<int>(m.promotion);
        }
        next.ep=m.flag==MoveFlag::double_push?(a+b)/2:0;
        for(int c=0;c<2;++c) for(int w=0;w<2;++w) {
            auto& right=next.rooks[static_cast<std::size_t>(c)][static_cast<std::size_t>(w)];
            if(right==a||right==b||(std::abs(p)==6&&c==(turn==1?0:1))) right=0;
        }
        next.turn=-turn;return next;
    }
    Moves moves() const {
        Moves result;
        auto accept=[&](int a,int b,Kind promotion=Kind::none,MoveFlag flag=MoveFlag::normal) {
            Move m{convert(a),convert(b),promotion,flag};auto next=apply(m);
            if(!next.threatened(next.king(turn),-turn)) result.push_back(m);
        };
        auto pawn_move=[&](int a,int b,MoveFlag flag) {
            if(b/10==(turn==1?9:2)) for(auto k:{Kind::queen,Kind::rook,Kind::bishop,Kind::knight}) accept(a,b,k,flag);
            else accept(a,b,Kind::none,flag);
        };
        for(int a=21;a<=98;++a) {
            int pc=(*this)[a];if(pc==99||pc*turn<=0) continue;int k=std::abs(pc);
            if(k==1) {
                int t=a+turn*10;
                if((*this)[t]==0) {
                    pawn_move(a,t,MoveFlag::normal);
                    if(a/10==(turn==1?3:8)&&(*this)[t+turn*10]==0) accept(a,t+turn*10,Kind::none,MoveFlag::double_push);
                }
                for(int dx:{-1,1}) {
                    int b=t+dx;
                    if((*this)[b]!=99&&(*this)[b]*turn<0&&std::abs((*this)[b])!=6) pawn_move(a,b,MoveFlag::normal);
                    if(b==ep) accept(a,b,Kind::none,MoveFlag::en_passant);
                }
                continue;
            }
            std::array<int,8> directions{};std::size_t direction_count=0;
            auto append=[&](std::initializer_list<int> values){for(int value:values)directions[direction_count++]=value;};
            if(k==2)append({21,19,12,8,-8,-12,-19,-21});
            if(k==3||k==5||k==6)append({11,9,-9,-11});
            if(k==4||k==5||k==6)append({1,-1,10,-10});
            for(std::size_t direction=0;direction<direction_count;++direction) {
                int d=directions[direction];
                for(int b=a+d;(*this)[b]!=99;b+=d) {
                if((*this)[b]*turn>0||std::abs((*this)[b])==6) break;
                accept(a,b);if((*this)[b]||k==2||k==6) break;
                }
            }
        }
        for(int w=0;w<2;++w) if(castle(w)) accept(king(turn),rooks[turn==1?0:1][static_cast<std::size_t>(w)],Kind::none,MoveFlag::castle);
        return result;
    }
};
std::uint64_t visit(const Mailbox& b,int depth) {
    if(depth==0) return 1;
    auto moves=b.moves();if(depth==1) return moves.size();
    std::uint64_t n=0;for(auto m:moves) n+=visit(b.apply(m),depth-1);return n;
}
}
Moves legal(const Position& p) { return Mailbox(p).moves(); }
std::uint64_t perft(const Position& p,int d) {
    if(d<0||d>6) throw InputError("mailbox perft depth must be in [0,6]");
    return visit(Mailbox(p),d);
}
}
