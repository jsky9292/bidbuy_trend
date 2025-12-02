"""
비드바이코리아 트렌드 분석 & 뉴스레터 생성기
============================================
엑셀 파일을 넣으면:
1. 인기 검색어/주문 통계 추출
2. 전년 동월 대비 분석
3. AI 트렌드 분석 텍스트 생성
4. HTML 뉴스레터 자동 생성

사용법:
    python bidbuy_analyzer.py --input 판매데이터.xlsx --period weekly
    python bidbuy_analyzer.py --input 판매데이터.xlsx --period monthly --yoy 작년데이터.xlsx
"""

import pandas as pd
import json
from datetime import datetime, timedelta
from pathlib import Path
import argparse
import os

# ============================================
# 1. 데이터 로더
# ============================================

class DataLoader:
    """엑셀 파일에서 판매/검색 데이터 로드"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.df = None
        
    def load(self) -> pd.DataFrame:
        """엑셀 파일 로드 (다양한 형식 지원)"""
        file_ext = Path(self.file_path).suffix.lower()
        
        if file_ext in ['.xlsx', '.xls']:
            self.df = pd.read_excel(self.file_path)
        elif file_ext == '.csv':
            # 인코딩 자동 감지
            for encoding in ['utf-8', 'cp949', 'euc-kr']:
                try:
                    self.df = pd.read_csv(self.file_path, encoding=encoding)
                    break
                except:
                    continue
        else:
            raise ValueError(f"지원하지 않는 파일 형식: {file_ext}")
        
        # 컬럼명 정규화
        self.df.columns = self.df.columns.str.strip().str.lower()
        
        print(f"✅ 데이터 로드 완료: {len(self.df)}행")
        print(f"   컬럼: {list(self.df.columns)}")
        
        return self.df
    
    def detect_columns(self) -> dict:
        """컬럼 자동 매핑 (다양한 컬럼명 대응)"""
        column_map = {
            'keyword': None,      # 검색어/상품명
            'count': None,        # 검색량/주문량
            'category': None,     # 카테고리
            'date': None,         # 날짜
            'price': None,        # 가격
            'product_name': None  # 상품명
        }
        
        # 검색어/상품명 컬럼 찾기
        keyword_candidates = ['검색어', 'keyword', '상품명', 'product', '품명', '제품명', 'item']
        for col in self.df.columns:
            if any(k in col for k in keyword_candidates):
                column_map['keyword'] = col
                break
        
        # 수량 컬럼 찾기
        count_candidates = ['검색량', 'count', '주문량', '수량', 'quantity', '건수', '횟수', 'orders']
        for col in self.df.columns:
            if any(k in col for k in count_candidates):
                column_map['count'] = col
                break
        
        # 카테고리 컬럼 찾기
        category_candidates = ['카테고리', 'category', '분류', '대분류', '중분류']
        for col in self.df.columns:
            if any(k in col for k in category_candidates):
                column_map['category'] = col
                break
        
        # 날짜 컬럼 찾기
        date_candidates = ['날짜', 'date', '주문일', '검색일', '일자', 'order_date']
        for col in self.df.columns:
            if any(k in col for k in date_candidates):
                column_map['date'] = col
                break
        
        # 가격 컬럼 찾기
        price_candidates = ['가격', 'price', '금액', '단가', 'amount', '엔', 'jpy', '원']
        for col in self.df.columns:
            if any(k in col for k in price_candidates):
                column_map['price'] = col
                break
        
        print(f"📋 컬럼 매핑: {column_map}")
        return column_map


# ============================================
# 2. 데이터 분석기
# ============================================

class TrendAnalyzer:
    """판매/검색 트렌드 분석"""
    
    def __init__(self, df: pd.DataFrame, column_map: dict):
        self.df = df
        self.col = column_map
        
    def get_top_keywords(self, n: int = 20) -> pd.DataFrame:
        """인기 검색어/상품 TOP N"""
        if not self.col['keyword'] or not self.col['count']:
            # count 컬럼이 없으면 빈도수로 계산
            if self.col['keyword']:
                top = self.df[self.col['keyword']].value_counts().head(n).reset_index()
                top.columns = ['keyword', 'count']
                return top
            return pd.DataFrame()
        
        top = self.df.groupby(self.col['keyword'])[self.col['count']].sum()
        top = top.sort_values(ascending=False).head(n).reset_index()
        top.columns = ['keyword', 'count']
        return top
    
    def get_category_stats(self) -> pd.DataFrame:
        """카테고리별 통계"""
        if not self.col['category']:
            return pd.DataFrame()
        
        if self.col['count']:
            stats = self.df.groupby(self.col['category'])[self.col['count']].sum()
        else:
            stats = self.df[self.col['category']].value_counts()
        
        stats = stats.sort_values(ascending=False).reset_index()
        stats.columns = ['category', 'count']
        return stats
    
    def get_rising_keywords(self, prev_df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
        """전기 대비 급상승 키워드"""
        if not self.col['keyword']:
            return pd.DataFrame()
        
        # 현재 기간 집계
        if self.col['count']:
            current = self.df.groupby(self.col['keyword'])[self.col['count']].sum()
        else:
            current = self.df[self.col['keyword']].value_counts()
        
        # 이전 기간 집계
        if self.col['count']:
            previous = prev_df.groupby(self.col['keyword'])[self.col['count']].sum()
        else:
            previous = prev_df[self.col['keyword']].value_counts()
        
        # 변화율 계산
        combined = pd.DataFrame({
            'current': current,
            'previous': previous
        }).fillna(0)
        
        combined['change_rate'] = ((combined['current'] - combined['previous']) / 
                                   combined['previous'].replace(0, 1) * 100).round(1)
        
        # 급상승 (100% 이상 증가, 최소 검색량 기준 충족)
        rising = combined[
            (combined['change_rate'] >= 100) & 
            (combined['current'] >= combined['current'].quantile(0.3))
        ].sort_values('change_rate', ascending=False).head(n)
        
        return rising.reset_index()
    
    def generate_summary(self) -> dict:
        """분석 요약 생성"""
        summary = {
            'total_records': len(self.df),
            'top_keywords': self.get_top_keywords(20).to_dict('records'),
            'category_stats': self.get_category_stats().to_dict('records'),
            'analysis_date': datetime.now().strftime('%Y-%m-%d'),
        }
        
        # 1위 키워드
        if summary['top_keywords']:
            summary['top_1_keyword'] = summary['top_keywords'][0]['keyword']
            summary['top_1_count'] = summary['top_keywords'][0]['count']
        
        return summary


# ============================================
# 3. AI 콘텐츠 생성기
# ============================================

class ContentGenerator:
    """AI 기반 트렌드 분석 텍스트 생성"""
    
    def __init__(self, use_ai: bool = False):
        self.use_ai = use_ai
        
    def generate_trend_text(self, summary: dict) -> str:
        """트렌드 분석 텍스트 생성"""
        
        if self.use_ai:
            return self._generate_with_ai(summary)
        else:
            return self._generate_template(summary)
    
    def _generate_template(self, summary: dict) -> str:
        """템플릿 기반 텍스트 생성 (AI 없이)"""
        
        top_keywords = summary.get('top_keywords', [])[:5]
        categories = summary.get('category_stats', [])[:3]
        
        # 키워드 리스트
        keyword_list = ', '.join([k['keyword'] for k in top_keywords])
        
        # 카테고리 분석
        if categories:
            top_category = categories[0]['category']
            category_text = f"카테고리별로는 '{top_category}'가 가장 높은 관심을 받고 있습니다."
        else:
            category_text = ""
        
        text = f"""
이번 기간 비드바이 고객들의 검색 트렌드를 분석했습니다.

가장 많이 검색된 키워드는 '{summary.get('top_1_keyword', '-')}'로, 
총 {summary.get('top_1_count', 0):,}건의 검색이 발생했습니다.

TOP 5 인기 키워드: {keyword_list}

{category_text}

20년간의 데이터를 바탕으로 엄선한 인기 상품들을 
비드바이 셀렉트에서 만나보세요!
        """.strip()
        
        return text
    
    def _generate_with_ai(self, summary: dict) -> str:
        """Claude API로 텍스트 생성"""
        try:
            import anthropic
            
            client = anthropic.Anthropic()
            
            prompt = f"""
당신은 비드바이코리아의 일본 구매대행 트렌드 분석가입니다.
다음 데이터를 바탕으로 고객에게 보낼 뉴스레터 본문을 작성해주세요.

데이터:
- 분석 기간: {summary.get('analysis_date')}
- 총 데이터: {summary.get('total_records'):,}건
- TOP 10 인기 키워드: {json.dumps(summary.get('top_keywords', [])[:10], ensure_ascii=False)}
- 카테고리 통계: {json.dumps(summary.get('category_stats', [])[:5], ensure_ascii=False)}

작성 규칙:
1. 친근하지만 전문가다운 톤
2. 300자 내외로 간결하게
3. "왜 이 키워드가 인기인지" 맥락 설명
4. 구매 행동 유도하는 문구 포함
5. 이모지 2-3개 적절히 활용
            """
            
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            
            return response.content[0].text
            
        except Exception as e:
            print(f"⚠️ AI 생성 실패, 템플릿 사용: {e}")
            return self._generate_template(summary)


# ============================================
# 4. 뉴스레터 HTML 생성기
# ============================================

class NewsletterGenerator:
    """HTML 뉴스레터 생성"""
    
    def __init__(self, summary: dict, trend_text: str):
        self.summary = summary
        self.trend_text = trend_text
        
    def generate_html(self) -> str:
        """뉴스레터 HTML 생성"""
        
        top_keywords = self.summary.get('top_keywords', [])[:10]
        categories = self.summary.get('category_stats', [])[:5]
        
        # 키워드 테이블 행 생성
        keyword_rows = ""
        for i, kw in enumerate(top_keywords, 1):
            trend_icon = "🔥" if i <= 3 else "📈" if i <= 5 else ""
            keyword_rows += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: center; font-weight: bold; color: #e74c3c;">{i}</td>
                <td style="padding: 12px; border-bottom: 1px solid #eee;">{kw['keyword']} {trend_icon}</td>
                <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right; color: #7f8c8d;">{kw['count']:,}건</td>
            </tr>
            """
        
        # 카테고리 바 생성
        category_bars = ""
        if categories:
            max_count = categories[0]['count']
            for cat in categories:
                width = int((cat['count'] / max_count) * 100)
                category_bars += f"""
                <div style="margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                        <span>{cat['category']}</span>
                        <span style="color: #7f8c8d;">{cat['count']:,}</span>
                    </div>
                    <div style="background: #ecf0f1; border-radius: 4px; height: 8px;">
                        <div style="background: linear-gradient(90deg, #3498db, #2ecc71); width: {width}%; height: 100%; border-radius: 4px;"></div>
                    </div>
                </div>
                """
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>비드바이 주간 트렌드</title>
</head>
<body style="margin: 0; padding: 0; font-family: 'Malgun Gothic', sans-serif; background: #f5f5f5;">
    <div style="max-width: 600px; margin: 0 auto; background: #ffffff;">
        
        <!-- 헤더 -->
        <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 30px 20px; text-align: center;">
            <h1 style="margin: 0 0 10px 0; font-size: 24px;">📊 비드바이 주간 트렌드</h1>
            <p style="margin: 0; opacity: 0.8; font-size: 14px;">{self.summary.get('analysis_date')} 기준 | 20년 데이터 기반 분석</p>
        </div>
        
        <!-- 1위 하이라이트 -->
        <div style="background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%); color: white; padding: 25px 20px; text-align: center;">
            <p style="margin: 0 0 5px 0; font-size: 14px; opacity: 0.9;">🔥 이번 주 검색 1위</p>
            <h2 style="margin: 0; font-size: 28px;">{self.summary.get('top_1_keyword', '-')}</h2>
            <p style="margin: 10px 0 0 0; font-size: 14px; opacity: 0.9;">{self.summary.get('top_1_count', 0):,}건 검색</p>
        </div>
        
        <!-- 인기 검색어 TOP 10 -->
        <div style="padding: 25px 20px;">
            <h3 style="margin: 0 0 15px 0; color: #2c3e50; font-size: 18px;">📈 인기 검색어 TOP 10</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="background: #f8f9fa;">
                        <th style="padding: 12px; text-align: center; font-size: 14px; color: #7f8c8d; width: 50px;">순위</th>
                        <th style="padding: 12px; text-align: left; font-size: 14px; color: #7f8c8d;">키워드</th>
                        <th style="padding: 12px; text-align: right; font-size: 14px; color: #7f8c8d; width: 80px;">검색량</th>
                    </tr>
                </thead>
                <tbody>
                    {keyword_rows}
                </tbody>
            </table>
        </div>
        
        <!-- 카테고리 통계 -->
        {"<div style='padding: 0 20px 25px 20px;'><h3 style='margin: 0 0 15px 0; color: #2c3e50; font-size: 18px;'>📦 카테고리별 인기도</h3>" + category_bars + "</div>" if category_bars else ""}
        
        <!-- 트렌드 분석 -->
        <div style="background: #f8f9fa; padding: 25px 20px; margin: 0 20px; border-radius: 8px;">
            <h3 style="margin: 0 0 15px 0; color: #2c3e50; font-size: 18px;">💡 이번 주 트렌드 분석</h3>
            <p style="margin: 0; line-height: 1.7; color: #34495e; font-size: 15px; white-space: pre-line;">{self.trend_text}</p>
        </div>
        
        <!-- CTA 버튼 -->
        <div style="padding: 30px 20px; text-align: center;">
            <a href="#" style="display: inline-block; background: linear-gradient(135deg, #6c5ce7 0%, #a29bfe 100%); color: white; padding: 15px 40px; text-decoration: none; border-radius: 30px; font-weight: bold; font-size: 16px;">
                🛒 인기 상품 바로 보기
            </a>
            <p style="margin: 15px 0 0 0; font-size: 13px; color: #95a5a6;">비드바이 셀렉트에서 확인하세요</p>
        </div>
        
        <!-- 푸터 -->
        <div style="background: #2c3e50; color: white; padding: 20px; text-align: center; font-size: 12px;">
            <p style="margin: 0 0 10px 0; opacity: 0.9;">비드바이코리아 | 20년 전통 일본 구매대행</p>
            <p style="margin: 0; opacity: 0.6;">본 메일은 정보 제공 목적으로 발송되었습니다.</p>
        </div>
        
    </div>
</body>
</html>
        """
        
        return html
    
    def save_html(self, output_path: str):
        """HTML 파일 저장"""
        html = self.generate_html()
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"✅ 뉴스레터 저장: {output_path}")
        return output_path


# ============================================
# 5. 리포트 생성기
# ============================================

class ReportGenerator:
    """분석 리포트 생성 (엑셀/JSON)"""
    
    def __init__(self, summary: dict, analyzer: TrendAnalyzer):
        self.summary = summary
        self.analyzer = analyzer
        
    def save_excel(self, output_path: str):
        """엑셀 리포트 저장"""
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # 인기 키워드
            pd.DataFrame(self.summary['top_keywords']).to_excel(
                writer, sheet_name='인기키워드_TOP20', index=False
            )
            
            # 카테고리 통계
            if self.summary['category_stats']:
                pd.DataFrame(self.summary['category_stats']).to_excel(
                    writer, sheet_name='카테고리_통계', index=False
                )
            
            # 요약 정보
            summary_df = pd.DataFrame([{
                '분석일': self.summary['analysis_date'],
                '총 데이터': self.summary['total_records'],
                '1위 키워드': self.summary.get('top_1_keyword', ''),
                '1위 검색량': self.summary.get('top_1_count', 0),
            }])
            summary_df.to_excel(writer, sheet_name='요약', index=False)
            
        print(f"✅ 리포트 저장: {output_path}")
        return output_path
    
    def save_json(self, output_path: str):
        """JSON 리포트 저장"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.summary, f, ensure_ascii=False, indent=2)
        print(f"✅ JSON 저장: {output_path}")
        return output_path


# ============================================
# 6. 메인 실행
# ============================================

def main():
    parser = argparse.ArgumentParser(description='비드바이 트렌드 분석기')
    parser.add_argument('--input', '-i', required=True, help='입력 엑셀/CSV 파일')
    parser.add_argument('--yoy', help='전년 동월 비교용 파일 (선택)')
    parser.add_argument('--period', default='weekly', choices=['weekly', 'monthly'], help='분석 기간')
    parser.add_argument('--output', '-o', default='./output', help='출력 폴더')
    parser.add_argument('--ai', action='store_true', help='AI 텍스트 생성 사용')
    
    args = parser.parse_args()
    
    # 출력 폴더 생성
    output_dir = Path(args.output)
    output_dir.mkdir(exist_ok=True)
    
    print("\n" + "="*50)
    print("🚀 비드바이 트렌드 분석기 시작")
    print("="*50 + "\n")
    
    # 1. 데이터 로드
    print("📂 데이터 로드 중...")
    loader = DataLoader(args.input)
    df = loader.load()
    column_map = loader.detect_columns()
    
    # 2. 데이터 분석
    print("\n📊 데이터 분석 중...")
    analyzer = TrendAnalyzer(df, column_map)
    summary = analyzer.generate_summary()
    
    # 전년 비교 (옵션)
    if args.yoy:
        print("\n📈 전년 동월 비교 분석 중...")
        yoy_loader = DataLoader(args.yoy)
        yoy_df = yoy_loader.load()
        rising = analyzer.get_rising_keywords(yoy_df)
        summary['rising_keywords'] = rising.to_dict('records') if not rising.empty else []
    
    # 3. 콘텐츠 생성
    print("\n✍️ 콘텐츠 생성 중...")
    content_gen = ContentGenerator(use_ai=args.ai)
    trend_text = content_gen.generate_trend_text(summary)
    
    # 4. 뉴스레터 HTML 생성
    print("\n📧 뉴스레터 생성 중...")
    newsletter = NewsletterGenerator(summary, trend_text)
    html_path = output_dir / f"newsletter_{summary['analysis_date']}.html"
    newsletter.save_html(str(html_path))
    
    # 5. 리포트 저장
    print("\n📋 리포트 저장 중...")
    report = ReportGenerator(summary, analyzer)
    report.save_excel(str(output_dir / f"report_{summary['analysis_date']}.xlsx"))
    report.save_json(str(output_dir / f"data_{summary['analysis_date']}.json"))
    
    # 6. 완료 메시지
    print("\n" + "="*50)
    print("✅ 분석 완료!")
    print("="*50)
    print(f"""
📊 분석 결과 요약:
   - 총 데이터: {summary['total_records']:,}건
   - 1위 키워드: {summary.get('top_1_keyword', '-')}
   - 1위 검색량: {summary.get('top_1_count', 0):,}건

📁 생성된 파일:
   - {html_path} (뉴스레터)
   - {output_dir}/report_{summary['analysis_date']}.xlsx (리포트)
   - {output_dir}/data_{summary['analysis_date']}.json (데이터)
    """)
    
    return summary


if __name__ == "__main__":
    main()
