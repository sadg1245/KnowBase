import React, { useEffect, useMemo, useState } from 'react';
import { App, Button, Empty, Progress, Space, Typography } from 'antd';
import { CheckOutlined, CloseOutlined, EyeOutlined, MehOutlined, SmileOutlined } from '@ant-design/icons';
import { Flashcard, getCards, reviewCard } from '../services/api';
const {Title,Text,Paragraph}=Typography;

const ReviewCenter:React.FC=()=>{
 const {message}=App.useApp();
 const [cards,setCards]=useState<Flashcard[]>([]);const [index,setIndex]=useState(0);const [flipped,setFlipped]=useState(false);const [loading,setLoading]=useState(true);const [done,setDone]=useState(0);
 useEffect(()=>{getCards(true).then(setCards).catch(()=>message.error('复习卡片没有加载成功')).finally(()=>setLoading(false));},[]);
 const current=cards[index];const total=cards.length;const finish=async(rating:1|2|3|4)=>{if(!current)return;await reviewCard(current.id,rating);setDone(v=>v+1);setFlipped(false);setIndex(v=>v+1);};
 if(loading)return <div>正在准备今日卡片…</div>;
 if(!current)return <div><div className="page-eyebrow">Review · 间隔重复</div><Title className="page-title" level={1}>复习中心</Title><div className="paper-card empty-guide" style={{marginTop:32}}><div style={{fontSize:48,color:'#3f8f6b'}}><CheckOutlined/></div><Title level={3}>{done?'今天的卡片复习完成':'今天没有到期卡片'}</Title><Text type="secondary">{done?`你完成了 ${done} 张卡片。记忆会在下一次合适的时间再次出现。`:'从知识点或 AI 回答创建卡片后，它们会出现在这里。'}</Text></div></div>;
 return <div><div className="page-eyebrow">Review · 间隔重复</div><Space style={{width:'100%',justifyContent:'space-between'}} align="end"><div><Title className="page-title" level={1}>今日复习</Title><p className="page-lead">先尝试回忆，再翻开答案。诚实选择记忆感受，系统会安排下一次复习。</p></div><Text type="secondary">{index+1} / {total}</Text></Space><Progress percent={Math.round((index/total)*100)} showInfo={false} strokeColor="#167d8d" style={{marginTop:24}}/>
 <div role="button" tabIndex={0} onClick={()=>setFlipped(v=>!v)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' ')setFlipped(v=>!v)}} className="paper-card" style={{maxWidth:760,minHeight:390,margin:'35px auto 24px',padding:'52px clamp(25px,7vw,80px)',display:'flex',flexDirection:'column',justifyContent:'center',textAlign:'center',cursor:'pointer',borderTop:'5px solid #167d8d'}}><Text type="secondary" style={{letterSpacing:'.12em'}}>{flipped?'答案':'问题'}</Text><Title level={2} style={{margin:'24px 0',lineHeight:1.55}}>{flipped?current.back:current.front}</Title>{flipped&&current.source_label&&<Text type="secondary">来源：{current.source_label}</Text>}{!flipped&&<Button type="text" icon={<EyeOutlined/>}>想好后点击查看答案</Button>}</div>
 {flipped&&<Space wrap style={{width:'100%',justifyContent:'center'}} size="middle"><Button size="large" danger icon={<CloseOutlined/>} onClick={()=>finish(1)}>忘记了</Button><Button size="large" icon={<MehOutlined/>} onClick={()=>finish(2)}>有点模糊</Button><Button size="large" type="primary" icon={<CheckOutlined/>} onClick={()=>finish(3)}>记住了</Button><Button size="large" style={{borderColor:'#3f8f6b',color:'#3f8f6b'}} icon={<SmileOutlined/>} onClick={()=>finish(4)}>非常熟练</Button></Space>}
 </div>;
};
export default ReviewCenter;
