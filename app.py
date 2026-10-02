import streamlit as st
from google import genai
from google.genai.errors import APIError
from PIL import Image, ImageDraw
import os
import io
import re
import json
import pandas as pd
from datetime import datetime

# Supabase 클라우드 DB 라이브러리
try:
    from supabase import create_client, Client
    HAS_SUPABASE_LIB = True
except ImportError:
    HAS_SUPABASE_LIB = False

# PIL 고화질 필터 호환성 설정
RESAMPLE_FILTER = getattr(Image, 'LANCZOS', getattr(Image, 'Resampling', Image).LANCZOS if hasattr(Image, 'Resampling') else Image.BICUBIC)

# ----------------------------------------------------
# 0-1. 스마트폰 카메라 기종별 보정 프로필 데이터베이스
# ----------------------------------------------------
CAMERA_PROFILES = {
    "애플 (Apple)": {
        "iPhone 17 / Pro / Max (최신)": "애플 Smart HDR 6 적용 (자연스러운 색감, 특유의 웜톤/노란기 미세 영점 보정, 펄 입자 정밀 분석)",
        "iPhone 16 / Pro / Max": "애플 Photonic Engine 적용 (특유의 웜톤 화이트밸런스 차감 보정)",
        "iPhone 15 시리즈": "애플 Smart HDR 5 적용 (온색계열 렌즈 화세 보정)",
        "iPhone 14 / Pro (기본)": "애플 Deep Fusion 적용 (기본 웜톤 및 입자 텍스처 보정)",
        "기타 아이폰": "아이폰 표준 렌즈 색감 보정"
    },
    "삼성 (Samsung)": {
        "Galaxy S26 / Ultra (최신)": "삼성 ProVisual Engine 적용 (인공 고채도/원색 강조 차감 보정, 샤프닝 억제 정밀 분석)",
        "Galaxy S25 / Ultra": "삼성 ProVisual Engine 적용 (고채도 및 명암 대비 영점 보정)",
        "Galaxy S24 / Ultra": "삼성 Nightography & ISP (선명한 색감 및 원색 강조 보정)",
        "Galaxy S23 / S22 시리즈": "삼성 씬 오프티마이저 (채도 보정 및 에지 강조 보정)",
        "Galaxy Z Fold / Flip 시리즈": "삼성 폴더블 전용 센서 특성 보정",
        "기타 갤럭시": "갤럭시 표준 렌즈 색감 보정"
    },
    "기타 브랜드": {
        "표준 스마트폰 (보정 기본)": "표준 RGB/CIE L*a*b* 하드웨어 렌즈 보정 기준 적용"
    }
}

# ----------------------------------------------------
# 0-2. 7대 도료사별 마스터 안료 코드 & 특성 데이터베이스
# ----------------------------------------------------
BRAND_CONFIGS = {
    "WATER-Q (노루페인트)": {
        "code_prefix": "Q-Code",
        "regex_pattern": r"(Q-\d{3,4})\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "WATER-Q 수성 전용 희석제 규정 비율(10~20%) 준수",
        "special_rules": "Q-7000 사용 시 배합 내 10% 초과 금지(초과 시 Q-7800/Q-7900 고은폐 백색 대체). Q-3550 메탈릭 금지, Q-7350 솔리드 금지.",
        "code_example": "Q-9760: 88.0g, Q-9800: 60.3g",
        "pigments": [
            "Q-0130 (적색착색마이카)", "Q-0170 (적색간섭마이카)", "Q-0180 (적색착색마이카)", "Q-0220 (오렌지착색실버마이카)", 
            "Q-0230 (오렌지착색실버마이카)", "Q-0270 (오렌지대입자마이카)", "Q-0330 (골드간섭마이카)", "Q-0350 (골드메탈릭마이카)", 
            "Q-0370 (골드착색마이카)", "Q-0380 (골드간섭마이카)", "Q-0410 (그린착색마이카)", "Q-0450 (그린간섭마이카)", 
            "Q-0470 (그린간섭마이카)", "Q-0480 (그린간섭마이카)", "Q-0490 (그린간섭마이카)", "Q-0510 (청색메탈릭마이카)", 
            "Q-0530 (청색마이카)", "Q-0550 (청색간섭마이카)", "Q-0560 (청색마이카)", "Q-0570 (청색선명간섭마이카)", 
            "Q-0610 (바이올렛마이카)", "Q-0620 (바이올렛그린마이카)", "Q-0650 (바이올렛마이카)", "Q-0710 (백색마이카)", 
            "Q-0720 (백색소입자마이카)", "Q-0730 (백색대입자마이카)", "Q-0750 (백색소입자마이카)", "Q-0760 (백색표준마이카)", 
            "Q-0770 (백색대입자마이카)", "Q-1350 (마젠타적색)", "Q-1500 (표준적색)", "Q-1510 (고채도핑크마젠타)", 
            "Q-1550 (선명핑크적색)", "Q-1630 (밝은황적색)", "Q-1650 (선명황적색)", "Q-1790 (밝은마룬적색)", 
            "Q-1800 (밝은마룬적색)", "Q-1950 (투명황등빛적색)", "Q-2300 (표준오렌지)", "Q-2400 (밝은오렌지)", 
            "Q-2500 (선명황동오렌지)", "Q-3350 (오렌지황색)", "Q-3400 (오렌지황색)", "Q-3550 (옥사이드황색-솔리드전용)", 
            "Q-3650 (투명골드황색)", "Q-3760 (표준황색)", "Q-3970 (강한녹미황색)", "Q-3980 (그린골드황색)", 
            "Q-4350 (표준녹색)", "Q-4450 (밝은황미녹색)", "Q-5300 (녹미청색)", "Q-5350 (녹미청색)", 
            "Q-5450 (표준청색)", "Q-5500 (표준청색)", "Q-5600 (선명적미청색)", "Q-5800 (표준적미청색)", 
            "Q-5830 (고채도울트라마린)", "Q-6450 (표준바이올렛)", "Q-7000 (표준백색-10%제한)", "Q-7350 (마이크로백색-메탈릭전용)", 
            "Q-7450 (각조정제-10%제한)", "Q-7800 (고농도고은폐백색)", "Q-7900 (고농도고은폐백색)", "Q-8000 (고혹색도흑색)", 
            "Q-8200 (표준흑색)", "Q-8350 (표준흑색)", "Q-8800 (우수흑색도흑색)", "Q-9260 (최소입자실버)", 
            "Q-9300 (작은입자실버)", "Q-9360 (작은입자실버)", "Q-9380 (중간입자실버)", "Q-9420 (중간입자실버)", 
            "Q-9460 (중간입자실버)", "Q-9500 (중간입자실버)", "Q-9560 (중간입자실버)", "Q-9600 (중간입자실버)", 
            "Q-9660 (큰입자실버)", "Q-9700 (큰입자실버)", "Q-9760 (큰입자실버)", "Q-9800 (중간입자스파클링실버)", 
            "Q-9880 (큰입자스파클링실버)", "Q-9890 (최대입자스파클링실버)"
        ]
    },
    "시켄스 오토웨이브 옵티마 (노루/Sikkens Optima)": {
        "code_prefix": "Optima 토너 코드",
        "regex_pattern": r"([W|Z|Y|V|B|G|R|O|M|P|C|S][A-Za-z0-9\-]+)\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "표준 희석제 10% ~ 15% 정확 혼합 준수 (C063/C070/C100 수칙)",
        "special_rules": "W110 20% 초과 시 고농축 W120 전환. Z1070 저농도 환산(Z160 1g=Z1070 16.67g). Y4050/Y4060/B6020/G5030/R2040 저농도 환산비 적용. SE8SA 크롬 이펙트 초박막 도포.",
        "code_example": "W110: 80.0g, C070: 10.0g, M85B: 10.0g",
        "pigments": [
            "C063 (Converter)", "C070 (Flop Controller)", "C100 (3-Coat Midcoat Binder)", 
            "W101 (White Transp.)", "W110 (White Standard)", "W120 (White High Strength)", 
            "Z1070 (Mixing Black-Low)", "Z145 (Deep Black)", "Z147 (Deep Black Effect)", "Z160 (Mixing Black)", 
            "Y4050 (Low Yellow-Y437)", "Y4060 (Low Yellow-Y455)", "Y432 (Green Yellow Transp.)", 
            "Y435 (Bright Yellow Solid)", "Y436 (Yellow Orange Transp.)", "Y437 (Yellow Orange Solid)", 
            "Y438 (Yellow Solid)", "Y439 (Yellow Metallic Transp.)", "Y455 (Yellow Solid)", 
            "V725 (Red Violet Transp.)", "V726 (Red Violet Solid)", "V727 (Red Violet Solid Transp.)", "V766 (Blue Violet Transp.)", 
            "B6020 (Low Blue-B673)", "B652 (Blue Green Transp.)", "B671 (Blue Green Transp.)", 
            "B673 (Blue Violet Transp.)", "B679 (Blue Violet Transp.)", "G5030 (Low Green-G550)", 
            "G550 (Green Yellow Transp.)", "G564 (Green Blue Transp.)", "O325 (Orange Red Transp.)", 
            "R2040 (Low Red-R239)", "R231 (Red Orange Solid)", "R233 (Orange Red Metallic)", 
            "R235 (Red Orange Transp.)", "R237 (Red Orange Transp.)", "R239 (Red Orange Solid/Met)", "R271 (Red Violet Transp.)", 
            "M85B (Metallic Fine Bright)", "M85E (Metallic Fine)", "M85F (SEC Fine Metallic)", 
            "M85J (Metallic Sparkle)", "M85M (Metallic Sparkle Coarse)", "M85P (Metallic Coarse)", "M85R (Metallic Extra Coarse)", 
            "M88H (Yellow Metallic)", "SE60A (SEC Orange Aluminum)", "SE6RA (SEC Red Aluminum)", 
            "SE6RT (SEC UF Red to Violet)", "SE6VT (SEC UF Violet to Red)", "SE6VX (SEC Violet to Red XF)", 
            "SE7BA (SEC Blue to Red)", "SE7BB (SEC Cyan to Purple)", "SE7GA (SEC Green to Purple)", 
            "SE7RA (SEC Red to Gold)", "SE7RB (SEC Magenta to Gold)", "SE7WA (SEC Silver to Green)", 
            "SE7YA (SEC Gold to Silver)", "SE8NB (SEC Orange Metallic)", "SE8NC (SEC Coarse Sparkle Silver)", 
            "SE8ND (SEC Blue Metallic)", "SE8NF (SEC Fine Sparkle Silver)", "SE8NM (SEC Medium Sparkle Silver)", 
            "SE8SA (Silver Argentum Chrome)", "SE9NA (SEC Lilac to Blue)", "SE9NB (Autumn Mystery)", 
            "SE9NC (SEC Green to Orange)", "SE9ND (SEC Lilac Sparkle)", "SE9NE (SEC Green Sparkle)", 
            "SE9NF (SEC Red Sparkle)", "SE9NG (SEC Turquoise to Gold)", "SE9NH (SEC Blue Sparkle)", "SE9NJ (Lapis Sunlight)", 
            "P11H (White Sparkle)", "P11M (White Pearl)", "P14C (White Pearl Extra Fine)", "P14F (White Pearl Fine)", 
            "P198 (Graphite)", "P22F (Red Pearl Fine)", "P22M (Red Pearl)", "P23H (Red Sparkle)", 
            "P25M (Red Violet Pearl)", "P33F (Copper Pearl Fine)", "P33M (Copper Pearl)", "P41F (Yellow Pearl Fine)", 
            "P41H (Yellow Sparkle)", "P41M (Yellow Pearl)", "P51F (Green Pearl Fine)", "P53M (Green Blue Pearl)", 
            "P54G (Green Blue Pearl)", "P54M (Green Pearl)", "P54S (Green Pearl Coarse)", "P61H (Blue Sparkle)", 
            "P64H (Blue Pearl Fine)", "P64R (Blue Pearl)", "P75S (Violet Blue Pearl)"
        ]
    },
    "시켄스 오토웨이브 2.0 (노루/Sikkens)": {
        "code_prefix": "MM 코드",
        "regex_pattern": r"(MM\s*\d{2,4}[A-Za-z]*)\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "Autowave 전용 수성 희석제 10~15% 혼합 및 에어 블로우 건조 수칙 준수",
        "special_rules": "MM 700(Flop Controller)은 배합 내 15% 이하 사용 엄격 제한(단독사용 금지). MM 600/666 수지 단독 사용 금지.",
        "code_example": "MM 800DF: 60.0g, MM 400: 20.0g",
        "pigments": [
            "MM 00 (화이트-비투과형)", "MM 098 (고농화이트-솔리드전용)", "MM 1001 (BLACK ED-저농)", "MM 1002 (BLUE ED-저농)", 
            "MM 101 (마이크로백색-반투과)", "MM 245 (Deep Black-딥블랙)", "MM 254 (오렌지-비투과)", "MM 266 (옐로우-투과형)", 
            "MM 296 (옐로우-비투과)", "MM 332BA (블루펄Fine-간섭)", "MM 332GA (그린펄-간섭)", "MM 332GB (그린펄Fine-간섭)", 
            "MM 332RA (레드펄-간섭)", "MM 332VA (바이올렛펄-간섭)", "MM 332XB (블루크실라릭Sparkle)", "MM 332XG (옐로우크실라릭Sparkle)", 
            "MM 332XS (화이트크실라릭Sparkle)", "MM 332YA (옐로우펄-간섭)", "MM 333P (화이트펄-중간입자)", "MM 333PB (블루펄-간섭)", 
            "MM 333PG (옐로우펄-간섭)", "MM 333PR (레드펄-착색)", "MM 334GA (그린펄-착색)", "MM 334GB (그린펄-착색)", 
            "MM 334PR (레드펄Fine-착색)", "MM 334RA (오렌지펄Fine-착색)", "MM 334RB (오렌지펄-착색)", "MM 334RE (그린펄-착색)", 
            "MM 334WA (화이트펄ExtraFine)", "MM 334WB (화이트펄Fine)", "MM 334XR (레드크실라릭Sparkle)", "MM 334ZA (그라파이트-펄전용)", 
            "MM 335 (옐로우-비투과)", "MM 342 (블루-투과형)", "MM 350 (바이올렛-투과형)", "MM 355 (레드-비투과)", 
            "MM 360 (레드-비투과)", "MM 361 (옐로우-반투과)", "MM 400 (표준블랙-Deep Black)", "MM 527 (레드-투과형)", 
            "MM 534 (블루-투과형)", "MM 537 (바이올렛-투과형)", "MM 558 (옐로우-비투과)", "MM 568 (레드-반투과)", 
            "MM 575 (블루-투과형)", "MM 577 (그린-투과형)", "MM 579 (옐로우-투과형)", "MM 599 (레드-투과형)", 
            "MM 600 (메탈릭원색용수지)", "MM 666 (3코트펄용수지)", "MM 700 (Flop Controller-15%제한)", "MM 732 (그린-투과형)", 
            "MM 744 (Mixing Black-조색용)", "MM 800MS (가장작은입자실버)", "MM 800C (작은입자실버)", "MM 800DF (중간입자실버-달러타입)", 
            "MM 800DC (큰입자실버-달러타입)", "MM 800CC (큰입자실버)", "MM 800EC (가장큰입자실버)", "MM 800YA (골드실버)", 
            "MM 952 (오렌지-투과형)", "MM 954 (바이올렛-투과형)", "MM 971 (바이올렛-투과형)", "MM 974 (오렌지-투과형)", "MM 980 (블루-투과형)"
        ]
    },
    "Glasurit 90Line (Glasurit)": {
        "code_prefix": "90-Line 코드",
        "regex_pattern": r"((?:90-[A-Za-z0-9\/]+|[A-Z]\d{2,3}[A-Z]*|M99\/\d{2}|M1))\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "93-E3 (표준) / 93-E10 (고온) 전용 희석제 50% 정확 혼합",
        "special_rules": "Abtöntabelle 정측면 보정 매트릭스 및 Multi-Effekt 펄 이동 수칙 적용. M1 Flop Control 입자 배향 제어. 93-E3/E10 50% 희석비 엄수.",
        "code_example": "90-M4: 70.0g, A031: 15.0g, M1: 5.0g",
        "pigments": [
            "90-3A0 (Cherry Red Transp.)", "A031 (White Opaque)", "A032 (White Opaque)", "A035 (Snow White Opaque)", 
            "A097 (Transparent White)", "A105 (Ochre Opaque)", "A115 (Yellow Transp.)", "A136 (Golden Ochre Transp.)", 
            "A143 (Yellow Transp.)", "A148 (Lemon Gold Opaque)", "A149 (Lemon Yellow Opaque)", "A177 (Organic Yellow Opaque)", 
            "A201 (Bright Orange Opaque)", "A306 (Red Iron Oxide Opaque)", "A307 (Red Opaque)", "A323 (High Strength Red Opaque)", 
            "A329 (Red Transp.)", "A347 (Maroon Transp.)", "A349 (Red Transp.)", "A350 (Dark Red Transp.)", 
            "A359 (Pink Transp.)", "A372 (Scarlet Orange Transp.)", "A378 (Red Transp.)", "A427 (Violet Transp.)", 
            "A430 (Red Violet Transp.)", "A503 (Blue Transp.)", "A527 (Midnight Blue II Transp.)", "A528 (Blue Transp.)", 
            "A563 (Green Shade Blue Transp.)", "A589 (Blue Transp.)", "A640 (Blue Green Transp.)", "A695 (Green Transp.)", 
            "A924 (Factory Black Opaque)", "A926 (Black Opaque)", "A927 (Low Strength Black Opaque)", "A997 (Jet Black Opaque)", 
            "E014 (Fine White Pearl 2)", "E025 (Sparkling Glass Transp.)", "E120 (Gold Glitter Sparkle)", "E220 (Orange Flash Pearl)", 
            "E280 (Brilliant Bronze Opaque)", "E330 (Flash Red Pearl)", "E435 (Crystal Shimmer Green)", "E440 (Violet Pearl)", 
            "E460 (Violet Shimmer)", "E480 (Violet Pearl Red)", "E520 (Blue Glitter Sparkle)", "E620 (Green Glitter Sparkle)", 
            "E630 (Moss Green Pearl)", "E650 (Super Green Pearl)", "E660 (Turquoise Pearl)", "E680 (Green-Red Pearl)", 
            "E820 (Bronze Pearl Copper)", "E830 (Copper Pearl)", "E850 (Copper Glitter Sparkle)", "E910 (Bright Brass Pearl)", 
            "E920 (Flash Gold Aluminum)", "E921 (Flash Gold Aluminum)", "M1 (Flop Control)", "M010 (White Pearl)", 
            "M011 (Fine White Pearl)", "M034K (Arctic White Opaque)", "M176 (Gold Pearl)", "M200K (Sun Orange Opaque)", 
            "M319 (Radiant Red Sparkle)", "M320K (Fire Red Opaque)", "M351K (Magma Red Transp.)", "M363 (Red Pearl Russet)", 
            "M364 (Fine Red Pearl Russet)", "M503K (Cobalt Blue Transp.)", "M505 (Blue Pearl)", "M506 (Fine Blue Pearl)", 
            "M527K (Ultramarine Transp.)", "M589K (Jeans Blue Transp.)", "M640K (Spring Green Transp.)", "M696K (Olive Green Transp.)", 
            "M919 (Crystal Silver Sparkle)", "M930 (Charcoal Black Opaque)", "M99/00 (Super Fine Aluminum)", "M99/01 (Extra Fine Aluminum)", 
            "M99/02 (Fine Aluminum)", "M99/03 (Medium Aluminum)", "M99/04 (Large Aluminum)", "M99/23 (Coarse Crystal Silver)", 
            "M99/24 (Fine Crystal Silver)"
        ]
    },
    "퍼마하이드 하이텍 (엑솔타/Spies Hecker)": {
        "code_prefix": "Hi-TEC WT 코드",
        "regex_pattern": r"(WT\s*\d{3,4})\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "WT 6050 (표준) / WT 6052 (저습도) 10%(솔리드) / 20%(이펙트) 혼합",
        "special_rules": "WT 385/387 컴포넌트 필수 투입. WT 386 Flop Control 적용. 단방향 1-Visit (1.5 횟수도포) 적용.",
        "code_example": "WT 321: 45.0g, WT 359: 15.0g",
        "pigments": [
            "WT 101 (Orange Radiant)", "WT 102 (Aluminum Pure Red)", "WT 112 (Magic Red)", "WT 144 (Green Blue)", 
            "WT 154 (Blue Effect)", "WT 188 (Super Deep Black)", "WT 197 (Ultra Fine Silver)", "WT 199 (Magic Ice Effect)", 
            "WT 300 (Transparent Maroon)", "WT 303 (Platinum Silver Extra Fine)", "WT 304 (Magic Sparkle)", "WT 308 (Bright Orange)", 
            "WT 309 (Brilliant Magenta)", "WT 311 (Ruby Red)", "WT 315 (Fine Blue Pearl)", "WT 318 (Brilliant Blue)", 
            "WT 320 (Platinum Pearl)", "WT 321 (White)", "WT 322 (Micro White)", "WT 323 (Special Black)", 
            "WT 324 (Reddish Yellow)", "WT 327 (Yellow)", "WT 328 (Ochre)", "WT 329 (Transparent Yellow)", 
            "WT 330 (Blood Orange)", "WT 331 (Translucent Oxide)", "WT 332 (Maroon)", "WT 333 (Granada Red)", 
            "WT 334 (Oxide Red)", "WT 335 (Dark Yellow)", "WT 336 (Translucent Red)", "WT 337 (Red)", 
            "WT 338 (Bluish Magenta)", "WT 339 (Violet)", "WT 340 (Yellow Magenta)", "WT 341 (Azure Blue)", 
            "WT 342 (Dark Violet)", "WT 343 (Blue)", "WT 344 (Dark Blue)", "WT 345 (Transparent Emerald)", 
            "WT 347 (Transparent Green)", "WT 348 (Transparent Azure)", "WT 349 (Translucent Green)", "WT 350 (Translucent Black)", 
            "WT 351 (Translucent Azure)", "WT 352 (Translucent White)", "WT 353 (Translucent Magenta)", "WT 354 (Fine Silver)", 
            "WT 355 (Brilliant Silver Coarse)", "WT 356 (Medium Silver)", "WT 357 (Micro Silver)", "WT 359 (Bright Silver)", 
            "WT 360 (Coarse Silver)", "WT 361 (Brilliant Silver)", "WT 362 (Brilliant Silver Fine)", "WT 363 (Brilliant Gold)", 
            "WT 364 (White Pearl)", "WT 365 (Lilac Pearl)", "WT 366 (Gold Pearl)", "WT 367 (Fine Green Pearl)", 
            "WT 368 (Fine White Pearl)", "WT 369 (Red Pearl)", "WT 370 (Bright Blue Pearl)", "WT 371 (Brown Pearl)", 
            "WT 372 (Fine Blue Pearl)", "WT 373 (Ruby Pearl)", "WT 374 (Blue Green Pearl)", "WT 375 (Green Pearl)", 
            "WT 376 (Red Pearl Extra)", "WT 377 (Diamond White)", "WT 378 (Diamond Red)", "WT 379 (Diamond Copper)", 
            "WT 380 (Diamond Green)", "WT 381 (Diamond Blue)", "WT 382 (Diamond Gold)", "WT 383 (Brilliant Orange)", 
            "WT 385 (System Component A)", "WT 386 (Flop Control)", "WT 387 (System Component B)", "WT 389 (Platinum Silver Fine)", 
            "WT 390 (Platinum Silver)", "WT 391 (Greenish Yellow)", "WT 393 (Light Yellow)", "WT 1500 (Ultra Deep Black)"
        ]
    },
    "R-M 오닉스 HD (삼화/R-M Onyx)": {
        "code_prefix": "Onyx 코드",
        "regex_pattern": r"([H|C]B\d{2,3}[A-Za-z]*)\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "Hydropure 전용 수성 희석제 규정 비율 준수",
        "special_rules": "Chromatic Color Wheel 기준 정측면 명도 제어. HB090 Flop Control 적용. HB203 Deep Black 흑색도 기준.",
        "code_example": "HB140: 60.0g, CB020: 30.0g",
        "pigments": [
            "HB010 (베이스화이트)", "HB020 (베이스블랙)", "HB030 (인디고)", "HB090 (Flop Control)", 
            "HB110 (Ultra Fine Aluminum)", "HB120 (Fine Aluminum)", "HB130 (Fine Aluminum)", "HB140 (Medium Aluminum)", 
            "HB150 (Medium Aluminum)", "HB176 (Medium Shiney Aluminum)", "HB186 (Coarse Shiney Aluminum)", "HB200 (Blue Black)", 
            "HB203 (Deep Black)", "HB250 (Standard Black)", "HB259 (Low Strength Black)", "HB260 (Satin Black)", 
            "HB300 (Carbazole Violet)", "HB444 (Blue)", "HB460 (Green Blue)", "HB464 (Sapphire Blue)", 
            "HB469 (Phthalo Blue II)", "HB471 (Phthalo Blue)", "HB540 (Blue-Green)", "HB564 (Yellow Green II)", 
            "HB600 (Green Gold)", "HB610 (Yellow)", "HB617 (Organic Yellow)", "HB619 (Light Yellow)", 
            "HB650 (Yellow Gold)", "HB670 (Yellow Oxide)", "HB680 (Gold)", "HB730 (Light Red)", 
            "HB740 (Bright Orange)", "HB770 (Red Oxide)", "HB779 (Red Oxide)", "HB780 (Red Gold)", 
            "HB821 (Bright Red)", "HB832 (Red II)", "HB855 (Light Maroon)", "HB860 (Red Maroon)", 
            "HB861 (Maroon)", "HB870 (Magenta)", "HB880 (Red Violet)", "HB961 (Transparent White)", 
            "HB990 (White)", "HB994 (Marble White)", "HB999 (Low Strength White)", "CB10K (Fine White Pearl 2)", 
            "CB12L (Crystal Glass Pearl)", "CB34M (Violet Pearl)", "CB35L (Ultra Violet)", "CB38K (Blackberry Pearl)", 
            "CB38L (Ultra White)", "CB45L (Blue Green Pearl)", "CB47M (Crystal Blue)", "CB54L (Green Pearl)", 
            "CB56L (Moss Green Pearl)", "CB57M (Crystal Green)", "CB58M (Red Green Pearl)", "CB62L (Crystal Gold)", 
            "CB63L (Super Brass Pearl)", "CB66V (Gold Aluminum)", "CB67V (Gold Aluminum)", "CB71V (Rich Bronze)", 
            "CB73L (Crystal Copper)", "CB74L (Bright Copper Pearl)", "CB75K (Orange Pearl)", "CB85L (Red Pearl)", 
            "CB87L (Flash Copper Pearl)", "SB202 (Deep Black II-Solvent)"
        ]
    },
    "수믹스 (KCC/Sumix)": {
        "code_prefix": "WT / K-코드",
        "regex_pattern": r"(K\d{3,4}|WT-\d{3,4})\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "KCC 수믹스 전용 수성 희석제 규정비 준수 (K9001/K9002/WT-100)",
        "special_rules": "K100 표준백색 메탈릭 혼합 금지. K101 저농도 백색 5% 이내 사용 제한. K102 정어둡/측밝 측면 보정용. K807 스파클링 실버 탁함 주의.",
        "code_example": "K100: 40.0g, K803: 30.0g, K902: 10.0g",
        "pigments": [
            "K100 (표준백색-순백솔리드)", "K101 (저농도백색-측면밝기5%이내)", "K102 (측면조절용백색-정어둡측밝)", "K200 (적색감청색)", 
            "K202 (녹색감청색)", "K203 (정적측녹청색)", "K204 (정녹측적청색)", "K205 (저농도청색-K204)", 
            "K300 (녹청색감녹색)", "K301 (저농도녹색-K300)", "K302 (녹황색감녹색)", "K400 (어두운녹황색)", 
            "K401 (밝은녹황색)", "K402 (솔리드황색)", "K403 (메탈릭황색-측면황녹)", "K404 (솔리드적황색)", 
            "K405 (솔리드황토색)", "K406 (저농도황색-K405)", "K407 (메탈릭황색-측면적감)", "K409 (솔리드황색)", 
            "K500 (밝은오렌지)", "K600 (보라적색)", "K601 (고은폐적색)", "K603 (밝은자홍적색)", 
            "K604 (최고밝은자홍적색)", "K605 (어두운자홍적색)", "K607 (황적색)", "K608 (은폐적색)", 
            "K609 (골드적색)", "K610 (어두운적황색)", "K611 (솔리드어두운적황색)", "K612 (핑크자홍적색)", 
            "K614 (밝은적색)", "K615 (적갈색)", "K616 (저농도적색-K608)", "K660 (고채도레드메탈릭)", 
            "K700 (표준흑색)", "K701 (저농도흑색-K700)", "K702 (고흑도황색감흑색)", "K703 (청색감흑색)", 
            "K800 (작은입자실버)", "K801 (가장작은입자실버)", "K802 (소입자실버)", "K803 (중간입자스파클링실버)", 
            "K804 (중간입자측면밝은실버)", "K805 (중간입자실버)", "K807 (최고스파클링큰입자실버)", "K808 (골드메탈릭실버)", 
            "K810 (최소입자실버)", "K814 (중간입자스파클링실버)", "K816 (최고정면밝은큰입자실버)", "K900 (최소화이트펄)", 
            "K901 (소입자화이트펄)", "K902 (중입자화이트펄)", "K903 (대입자화이트펄스파클링)", "K904 (소입자블루펄)", 
            "K905 (중입자블루착색펄)", "K906 (중입자블루펄)", "K907 (소입자바이올렛펄)", "K908 (대입자바이올렛펄스파클링)", 
            "K909 (소입자레드착색펄)", "K910 (중입자레드펄-흑바탕녹색)", "K911 (중입자레드착색펄)", "K912 (대입자레드착색펄스파클링)", 
            "K913 (중입자그린펄)", "K914 (중입자골드펄)", "K915 (대입자골드착색펄스파클링)", "K916 (중입자그린착색펄)", 
            "K917 (중입자오렌지착색펄)", "K918 (대입자블루펄스파클링)", "K919 (대입자그린펄스파클링)", "K920 (대입자오렌지착색펄스파클링)", 
            "K921 (대입자그린펄-각도변화)", "K922 (중입자레드착색펄-고채도)", "K923 (중입자블랙펄)", "K924 (소입자블루펄스파클링)", 
            "K925 (소입자그린펄)", "K926 (최대입자화이트펄스파클링)", "K927 (중입자레드펄)", "K990 (카멜레온펄-정녹/측보라)", 
            "K9001 (수믹스기본수지)", "K9002 (Baseclear수지)", "WT-100 (수성바인더)"
        ]
    },
    "엔바이로베이스 (PPG/Envirobase)": {
        "code_prefix": "EHP 코드",
        "regex_pattern": r"([T|P]\d{3,4}(?:-\d)?)\s*[:\=\|\s]+([\d\.]+)\s*g?",
        "thinner_info": "T494 (표준) / T495 (지건) + T492 Adjuster (10% Solid / 20% Effect / 30% Tri-coat)",
        "special_rules": "T403 Micro White 정측면 명도 반전 제어. T4000번대 스파클/플레이크 고채도 수칙 적용.",
        "code_example": "T400: 55.0g, P990-1: 20.0g",
        "pigments": [
            "T400 (Clean White)", "T402 (Trace White)", "T403 (Micro White)", "T404 (Trace Blue Black)", 
            "T405 (Graphite Black)", "T406 (Blue Black)", "T407 (Jet Black)", "T409 (Deep Black)", 
            "T411 (Bright Blue)", "T412 (Blue)", "T413 (Transparent Blue)", "T414 (Dark Blue)", 
            "T420 (Mid-shade Blue)", "T427 (Organic Yellow)", "T430 (Green)", "T431 (Yellow Green)", 
            "T432 (Transoxide Red)", "T433 (Bright Orange)", "T435 (Salmon Red)", "T436 (Red Oxide)", 
            "T438 (Rose)", "T440 (Trace Red Oxide)", "T441 (Carmine)", "T442 (Brown)", 
            "T443 (Violet)", "T444 (Yellow)", "T445 (Transparent Magenta)", "T447 (Bright Red)", 
            "T448 (Russet)", "T451 (Extra Fine White Pearl)", "T452 (Fine White Pearl)", "T453 (Standard White Pearl)", 
            "T454 (Bright Red Pearl)", "T455 (Fine Blue Pearl)", "T456 (Standard Blue Pearl)", "T457 (Green Pearl)", 
            "T460 (Yellow Pearl)", "T461 (Golden Yellow Pearl)", "T462 (Fine Red Pearl)", "T466 (Orange Pearl)", 
            "T468 (Violet Pearl)", "T471 (Extra Fine Silver)", "T472 (Fine Lenticular Silver)", "T474 (Fine Metallic)", 
            "T476 (Coarse Lenticular)", "T477 (Extra Coarse Silver)", "T479 (Extra Coarse Silver)", "T4000 (Crystal Silver)", 
            "T4001 (Sunbeam Gold)", "T4002 (Radiant Red)", "T4003 (Galaxy Blue)", "T4004 (Stellar Green)", 
            "T4007 (Cosmic Turquoise)", "T4008 (Amethyst Dream)", "T4018 (Prism Silver)", "T4031 (Arctic Fire)", 
            "T4034 (Tropic Sunrise)", "T4035 (Lapis Sunlight)", "T4040 (Orange Flash)", "T4042 (Blue Aluminum)", 
            "P990-1 (High Gloss Pearl)", "P990-2 (Violet Pearl)", "P991-1 (Gold Pearl)", "P992-1 (Flop Control)"
        ]
    }
}

# ----------------------------------------------------
# 1. 이미지 처리 & 배합표 카드 생성 함수
# ----------------------------------------------------
def load_and_resize(image_file_or_bytes, max_size=(2500, 2500)):
    if isinstance(image_file_or_bytes, bytes):
        img = Image.open(io.BytesIO(image_file_or_bytes))
    else:
        img = Image.open(image_file_or_bytes)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail(max_size, RESAMPLE_FILTER)
    return img

def crop_center(img, crop_ratio=0.4):
    w, h = img.size
    cw, ch = int(w * crop_ratio), int(h * crop_ratio)
    left = (w - cw) // 2
    top = (h - ch) // 2
    return img.crop((left, top, left + cw, top + ch))

def create_3way_split_view(bytes_prev, bytes_target, bytes_curr, crop_ratio=0.4):
    img_prev = load_and_resize(bytes_prev, max_size=(2500, 2500))
    img_target = load_and_resize(bytes_target, max_size=(2500, 2500))
    img_curr = load_and_resize(bytes_curr, max_size=(2500, 2500))
    
    crop1 = crop_center(img_prev, crop_ratio)
    crop_t = crop_center(img_target, crop_ratio)
    crop2 = crop_center(img_curr, crop_ratio)
    
    h = min(crop1.height, crop_t.height, crop2.height)
    w1 = int(crop1.width * (h / crop1.height))
    wt = int(crop_t.width * (h / crop_t.height))
    w2 = int(crop2.width * (h / crop2.height))
    
    c1_resized = crop1.resize((w1, h), RESAMPLE_FILTER)
    ct_resized = crop_t.resize((wt, h), RESAMPLE_FILTER)
    c2_resized = crop2.resize((w2, h), RESAMPLE_FILTER)
    
    merged_img = Image.new("RGB", (w1 + wt + w2, h))
    merged_img.paste(c1_resized, (0, 0))
    merged_img.paste(ct_resized, (w1, 0))
    merged_img.paste(c2_resized, (w1 + wt, 0))
    return merged_img

def create_recipe_image_card(brand_name, color_name, stage_code, recipe_df, total_weight, thinner_info, special_rules):
    if recipe_df is None or recipe_df.empty:
        rows = []
    else:
        rows = recipe_df.to_dict('records')
        
    num_rows = max(len(rows), 1)
    card_w = 800
    card_h = 240 + (num_rows + 1) * 45 + 160
    
    img = Image.new("RGB", (card_w, card_h), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    
    draw.rectangle([(0, 0), (card_w, 100)], fill=(9, 25, 54))
    draw.text((30, 22), "MULTI-BRAND AUTO COLOR SYSTEM", fill=(130, 177, 255))
    draw.text((30, 52), f"[{brand_name}] {stage_code} 조색 처방 리포트", fill=(255, 255, 255))
    
    draw.rectangle([(30, 115), (card_w - 30, 195)], fill=(235, 248, 255), outline=(49, 130, 206), width=2)
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    draw.text((45, 132), f"■ 차종 및 색상명/코드: {color_name if color_name else '미지정'}", fill=(15, 23, 42))
    draw.text((45, 162), f"■ 발행 일시: {today_str}   |   목표 배합 총 중량: {total_weight:.1f}g", fill=(15, 23, 42))
    
    table_top = 215
    draw.rectangle([(30, table_top), (card_w - 30, table_top + 40)], fill=(0, 51, 117))
    draw.text((50, table_top + 12), "안료 코드 (Pigment Code)", fill=(255, 255, 255))
    draw.text((420, table_top + 12), "배합 중량 (g)", fill=(255, 255, 255))
    draw.text((620, table_top + 12), "비율 (%)", fill=(255, 255, 255))
    
    curr_y = table_top + 40
    calc_total = sum([float(r.get("1차 배합 중량 (g)", 0) or 0) for r in rows]) if rows else 0.0
    
    for idx, r in enumerate(rows):
        bg_color = (255, 255, 255) if idx % 2 == 0 else (241, 245, 249)
        draw.rectangle([(30, curr_y), (card_w - 30, curr_y + 40)], fill=bg_color, outline=(226, 232, 240))
        code_val = str(r.get("안료 코드", "") or "")
        weight_val = float(r.get("1차 배합 중량 (g)", 0) or 0)
        ratio_val = (weight_val / calc_total * 100) if calc_total > 0 else 0.0
        
        draw.text((50, curr_y + 12), code_val, fill=(15, 23, 42))
        draw.text((420, curr_y + 12), f"{weight_val:.2f} g", fill=(15, 23, 42))
        draw.text((620, curr_y + 12), f"{ratio_val:.1f} %", fill=(71, 85, 105))
        curr_y += 40
        
    draw.rectangle([(30, curr_y), (card_w - 30, curr_y + 45)], fill=(226, 232, 240), outline=(148, 163, 184), width=2)
    draw.text((50, curr_y + 14), "합계 총 중량 (Total Weight)", fill=(15, 23, 42))
    draw.text((420, curr_y + 14), f"{calc_total:.2f} g", fill=(0, 51, 117))
    draw.text((620, curr_y + 14), "100.0 %", fill=(0, 51, 117))
    curr_y += 60
    
    draw.rectangle([(30, curr_y), (card_w - 30, curr_y + 75)], fill=(254, 243, 199), outline=(217, 119, 6), width=2)
    draw.text((45, curr_y + 15), f"희석 수칙: {thinner_info[:55]}", fill=(180, 83, 9))
    draw.text((45, curr_y + 42), f"특수 수칙: {special_rules[:55]}", fill=(180, 83, 9))
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def extract_recipe_df_from_ai_text(text, brand_name):
    if not text: return None
    try:
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not json_match: json_match = re.search(r"(\{[\s\S]*?\"[A-Za-z0-9\-\.]+\"[\s\S]*?\})", text)
        if json_match:
            data = json.loads(json_match.group(1))
            codes = [str(k).upper().strip() for k in data.keys()]
            weights = [float(v) for v in data.values()]
            if codes: return pd.DataFrame({"안료 코드": codes, "1차 배합 중량 (g)": weights})
    except Exception: pass

    pattern = BRAND_CONFIGS[brand_name]["regex_pattern"]
    matches = re.findall(pattern, text, re.IGNORECASE)
    if matches:
        codes, weights, seen = [], [], set()
        for m in matches:
            code = m[0].upper().strip()
            try:
                weight = float(m[1])
                if code not in seen and weight >= 0:
                    codes.append(code); weights.append(weight); seen.add(code)
            except Exception: continue
        if codes: return pd.DataFrame({"안료 코드": codes, "1차 배합 중량 (g)": weights})
    return None

def extract_df_from_recipe_image(client, image_bytes, brand_name):
    try:
        img = load_and_resize(image_bytes)
        prompt = f"""
        첨부된 [{brand_name}] 도료 배합표/시편 카드 이미지에서 안료 코드와 해당 중량(g)을 읽어 JSON으로만 출력하세요.
        ```json\n{{ "코드1": 88.0, "코드2": 60.31 }}\n```
        """
        res = client.models.generate_content(model="gemini-3.5-flash", contents=[img, prompt])
        return extract_recipe_df_from_ai_text(res.text, brand_name)
    except Exception as e:
        st.error(f"사진 인식 중 오류가 발생했습니다: {e}")
        return None

# ----------------------------------------------------
# 2. 페이지 설정 및 세션 단일 동기화 초기화
# ----------------------------------------------------
st.set_page_config(
    page_title="Multi-Brand AI Smart Color System",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded"
)

if "GEMINI_API_KEY" in st.secrets: api_key = st.secrets["GEMINI_API_KEY"]
else: st.error("⚠️ Secrets에 GEMINI_API_KEY가 없습니다."); st.stop()

client = genai.Client(api_key=api_key)

supabase_client = None
if HAS_SUPABASE_LIB and "SUPABASE_URL" in st.secrets and "SUPABASE_KEY" in st.secrets:
    try: supabase_client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    except Exception: pass

valid_brands = list(BRAND_CONFIGS.keys())
valid_phone_brands = list(CAMERA_PROFILES.keys())

if "pref_brand" not in st.session_state or st.session_state.pref_brand not in valid_brands:
    st.session_state.pref_brand = valid_brands[0]

if "pref_phone_brand" not in st.session_state or st.session_state.pref_phone_brand not in valid_phone_brands:
    st.session_state.pref_phone_brand = valid_phone_brands[0]

avail_models = list(CAMERA_PROFILES[st.session_state.pref_phone_brand].keys())
if "pref_phone_model" not in st.session_state or st.session_state.pref_phone_model not in avail_models:
    st.session_state.pref_phone_model = avail_models[0]

if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "current_user" not in st.session_state: st.session_state.current_user = ""
if "user_email" not in st.session_state: st.session_state.user_email = ""

if "current_stage" not in st.session_state: st.session_state.current_stage = 1
if "color_name" not in st.session_state: st.session_state.color_name = ""
if "color_name_input" not in st.session_state: st.session_state.color_name_input = ""
if "target_img_bytes" not in st.session_state: st.session_state.target_img_bytes = None
if "prev_sample_bytes" not in st.session_state: st.session_state.prev_sample_bytes = None
if "temp_sample_bytes" not in st.session_state: st.session_state.temp_sample_bytes = None

# ★ 초기에 완전히 비어있는 깨끗한 배합표 상태 제공 ★
if "recipe_table_df" not in st.session_state: 
    st.session_state.recipe_table_df = pd.DataFrame({"안료 코드": ["", "", "", ""], "1차 배합 중량 (g)": [0.0, 0.0, 0.0, 0.0]})

if "ai_result_text" not in st.session_state: st.session_state.ai_result_text = ""
if "show_next_btn" not in st.session_state: st.session_state.show_next_btn = False
if "is_passed" not in st.session_state: st.session_state.is_passed = False

def go_next_stage():
    st.session_state.current_stage += 1
    st.session_state.show_next_btn = False
    st.session_state.ai_result_text = ""
    st.session_state.is_passed = False
    if st.session_state.temp_sample_bytes is not None:
        st.session_state.prev_sample_bytes = st.session_state.temp_sample_bytes
        st.session_state.temp_sample_bytes = None

def reset_workspace():
    st.session_state.current_stage = 1
    st.session_state.color_name = ""
    st.session_state.color_name_input = ""
    st.session_state.target_img_bytes = None
    st.session_state.prev_sample_bytes = None
    st.session_state.temp_sample_bytes = None
    st.session_state.recipe_table_df = pd.DataFrame({"안료 코드": ["", "", "", ""], "1차 배합 중량 (g)": [0.0, 0.0, 0.0, 0.0]})
    st.session_state.ai_result_text = ""
    st.session_state.show_next_btn = False
    st.session_state.is_passed = False
    
    keys_to_delete = [k for k in st.session_state.keys() if k.startswith(("cam_", "file_", "editor_", "r_text_", "weight_", "lab_"))]
    for k in keys_to_delete:
        del st.session_state[k]

# ★ CSS: 모바일 화면 안료 표 한 화면 최적화 (가로 스크롤 제거) & 파란색 토글 버튼 ★
st.markdown("""<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] { font-family: 'Pretendard', -apple-system, sans-serif; }
    
    footer { visibility: hidden !important; display: none !important; }
    .stAppDeployButton { display: none !important; }
    div[data-testid="stDecoration"] { display: none !important; }
    [class*="viewerBadge"] { display: none !important; }
    iframe { display: none !important; }

    /* ★ stDataEditor 모바일 가로 너비 100% 자동 분할 (가로 스크롤 방지) ★ */
    [data-testid="stDataEditor"] {
        width: 100% !important;
        max-width: 100% !important;
    }
    [data-testid="stDataEditor"] > div {
        width: 100% !important;
    }

    /* ★ 사이드바 버튼 가시성 강화 ★ */
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarExpandControl"] {
        display: block !important;
        visibility: visible !important;
        z-index: 999999 !important;
    }
    
    [data-testid="stSidebarCollapsedControl"] button,
    [data-testid="stSidebarExpandControl"] button {
        background-color: #003375 !important;
        color: #FFFFFF !important;
        border: 2px solid #82B1FF !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
    }
    
    [data-testid="stSidebarCollapsedControl"] button svg,
    [data-testid="stSidebarExpandControl"] button svg {
        fill: #FFFFFF !important;
        color: #FFFFFF !important;
    }

    .noroo-header-box {
        background: linear-gradient(135deg, #091936 0%, #003375 50%, #005BB5 100%);
        padding: 22px 28px; border-radius: 16px; color: #FFFFFF;
        box-shadow: 0 8px 24px rgba(0, 51, 117, 0.18);
    }
    .noroo-brand-name { font-size: 13px; font-weight: 700; color: #82B1FF; letter-spacing: 2px; }
    .noroo-main-title { font-size: 23px; font-weight: 800; color: #FFFFFF; margin: 4px 0 0 0; }
    .stage-badge { background-color: #003375; color: #FFFFFF; padding: 6px 16px; border-radius: 20px; font-weight: 800; font-size: 15px; display: inline-block; margin-bottom: 15px; }
    .distance-guide-box { background-color: #EBF8FF; border-left: 4px solid #3182CE; padding: 10px 14px; border-radius: 6px; font-size: 13px; color: #2B6CB0; margin-bottom: 12px; }
    .comparison-card { background-color: #F8FAFC; border: 2px solid #005BB5; border-radius: 12px; padding: 18px; margin-bottom: 20px; }
    div.stButton > button[kind="primary"] { background: linear-gradient(135deg, #003375 0%, #005BB5 100%); color: white; border: none; padding: 14px 28px; font-size: 17px; font-weight: 700; border-radius: 10px; }
</style>""", unsafe_allow_html=True)

# ----------------------------------------------------
# 3. 로그인 모듈
# ----------------------------------------------------
if not st.session_state.logged_in:
    st.markdown("""<div class="noroo-header-box" style="text-align:center;">
        <span class="noroo-brand-name">MULTI-BRAND AUTO COLOR SYSTEM</span>
        <h1 class="noroo-main-title">🔐 Smart-Paint 클라우드 로그인</h1>
    </div>""", unsafe_allow_html=True)
    st.markdown("---")

    col_auth_center = st.columns([1, 1.2, 1])[1]
    with col_auth_center:
        auth_tab1, auth_tab2 = st.tabs(["🔑 로그인", "📝 테스터 회원가입"])
        
        with auth_tab1:
            saved_email_val = st.query_params.get("saved_email", "")
            remember_email_init = True if saved_email_val else False
            
            with st.form("login_form", clear_on_submit=False):
                login_email = st.text_input("이메일 (Email)", value=saved_email_val, key="login_email_input")
                login_pw = st.text_input("비밀번호 (Password)", type="password", key="login_pw_input")
                remember_email_chk = st.checkbox("☑️ 이메일(아이디) 기억하기", value=remember_email_init)
                submitted = st.form_submit_button("🚀 로그인하기", type="primary", use_container_width=True)
                
                if submitted:
                    if remember_email_chk: st.query_params["saved_email"] = login_email.strip()
                    else:
                        if "saved_email" in st.query_params: del st.query_params["saved_email"]
                            
                    login_success = False
                    if supabase_client:
                        try:
                            res = supabase_client.auth.sign_in_with_password({"email": login_email.strip(), "password": login_pw.strip()})
                            st.session_state.user_email = res.user.email
                            user_meta = res.user.user_metadata
                            st.session_state.current_user = user_meta.get("display_name", res.user.email.split("@")[0])
                            
                            if user_meta.get("pref_brand") in valid_brands: 
                                st.session_state.pref_brand = user_meta.get("pref_brand")
                            if user_meta.get("pref_phone_brand") in valid_phone_brands:
                                st.session_state.pref_phone_brand = user_meta.get("pref_phone_brand")
                                if user_meta.get("pref_phone_model") in CAMERA_PROFILES[st.session_state.pref_phone_brand]:
                                    st.session_state.pref_phone_model = user_meta.get("pref_phone_model")

                            login_success = True
                        except Exception:
                            st.error("❌ 로그인 실패: 이메일 또는 비밀번호를 확인하세요.")
                            
                        if login_success:
                            st.session_state.logged_in = True
                            st.rerun()
                    else:
                        if login_email == "admin@test.com" and login_pw == "1234":
                            st.session_state.logged_in = True; st.session_state.current_user = "관리자"; st.session_state.user_email = login_email; st.rerun()
                        else: 
                            st.error("❌ 아이디/비밀번호가 맞지 않습니다.")
        
        with auth_tab2:
            with st.form("register_form", clear_on_submit=False):
                reg_name = st.text_input("작업자 성함 / 공장명", key="reg_name_input")
                reg_email = st.text_input("사용할 이메일", key="reg_email_input")
                reg_pw = st.text_input("사용할 비밀번호 (6자리 이상)", type="password", key="reg_pw_input")
                reg_submitted = st.form_submit_button("📝 테스터 등록 신청", use_container_width=True)
                
                if reg_submitted:
                    if len(reg_pw.strip()) < 6: st.warning("⚠️ 비밀번호는 최소 6자리 이상이어야 합니다.")
                    elif supabase_client:
                        try:
                            supabase_client.auth.sign_up({"email": reg_email.strip(), "password": reg_pw.strip(), "options": {"data": {"display_name": reg_name.strip()}}})
                            st.success("🎉 가입 성공! [로그인] 탭에서 로그인해 주세요.")
                        except Exception as e: st.error(f"가입 실패: {e}")
    st.stop()

# ----------------------------------------------------
# 4. DB 저장 및 불러오기 함수
# ----------------------------------------------------
MAX_SAVE_LIMIT = 20

def db_fetch_user_history():
    if not supabase_client: return []
    try:
        res = supabase_client.table("work_history").select("*").eq("username", st.session_state.current_user).order("created_at", desc=True).execute()
        return res.data
    except Exception: return []

def db_save_work(title_name, current_brand):
    if not title_name.strip(): return False
    user_history = db_fetch_user_history()
    if supabase_client and len(user_history) >= MAX_SAVE_LIMIT:
        for old_item in user_history[MAX_SAVE_LIMIT - 1:]:
            try: supabase_client.table("work_history").delete().eq("id", old_item['id']).execute()
            except Exception: pass
            
    payload = {
        "username": st.session_state.current_user, "title": title_name.strip(), "brand": current_brand,
        "color_name": st.session_state.color_name, "stage": st.session_state.current_stage,
        "recipe_json": st.session_state.recipe_table_df.to_json(orient="records"),
        "ai_result": st.session_state.ai_result_text, "is_passed": st.session_state.is_passed
    }
    
    if supabase_client:
        try:
            supabase_client.table("work_history").insert(payload).execute()
            st.toast(f"☁️ '{title_name}' 저장 완료!", icon="💾")
            return True
        except Exception: return False
    return True

def db_get_successful_recipes_rag(brand_name, color_name):
    if not supabase_client or not color_name.strip(): return ""
    try:
        res = supabase_client.table("work_history").select("recipe_json, color_name, stage").eq("brand", brand_name).ilike("color_name", f"%{color_name.strip()}%").eq("is_passed", True).limit(3).execute()
        if not res.data: return ""
        txt = "\n\n[★ 과거 성공 레시피]\n"
        for i, r in enumerate(res.data, 1): txt += f" 사례{i} [{r['color_name']}]: {r['recipe_json']}\n"
        return txt
    except Exception: return ""

def db_delete_work(history_id):
    if supabase_client:
        try: supabase_client.table("work_history").delete().eq("id", history_id).execute()
        except Exception: pass

# ----------------------------------------------------
# 5. 좌측 사이드바 (단일 세션 동기화)
# ----------------------------------------------------
with st.sidebar:
    st.markdown(f"👤 **접속 계정**: `{st.session_state.current_user}`")
    st.caption(f"📧 `{st.session_state.user_email}`")
    if supabase_client: st.caption("🟢 **Supabase Auth & DB**: 연결 완료")
    if st.button("🔒 로그아웃", use_container_width=True):
        st.session_state.logged_in = False; st.rerun()

    st.markdown("---")
    
    # 1) 도료 브랜드 설정
    st.header("🎨 도료 브랜드 설정")
    b_idx = valid_brands.index(st.session_state.pref_brand)
    new_brand = st.selectbox("브랜드 변경", valid_brands, index=b_idx, key="sb_widget_brand")
    
    if new_brand != st.session_state.pref_brand:
        st.session_state.pref_brand = new_brand
        if "editor_active_recipe" in st.session_state:
            del st.session_state["editor_active_recipe"]
        if supabase_client and st.session_state.get("logged_in"):
            try: supabase_client.auth.update_user({"data": {"pref_brand": new_brand}})
            except Exception: pass
        st.rerun()
        
    st.info(f"📌 {BRAND_CONFIGS[st.session_state.pref_brand]['special_rules']}")

    st.markdown("---")

    # 2) 스마트폰 카메라 제조사 & 기종 설정
    st.header("📱 스마트폰 카메라 설정")
    pb_idx = valid_phone_brands.index(st.session_state.pref_phone_brand)
    new_p_brand = st.selectbox("제조사 선택", valid_phone_brands, index=pb_idx, key="sb_widget_phone_brand")
    
    if new_p_brand != st.session_state.pref_phone_brand:
        st.session_state.pref_phone_brand = new_p_brand
        new_avail_models = list(CAMERA_PROFILES[new_p_brand].keys())
        st.session_state.pref_phone_model = new_avail_models[0]
        if supabase_client and st.session_state.get("logged_in"):
            try: supabase_client.auth.update_user({"data": {"pref_phone_brand": new_p_brand, "pref_phone_model": new_avail_models[0]}})
            except Exception: pass
        st.rerun()

    curr_avail_models = list(CAMERA_PROFILES[st.session_state.pref_phone_brand].keys())
    if st.session_state.pref_phone_model not in curr_avail_models:
        st.session_state.pref_phone_model = curr_avail_models[0]

    pm_idx = curr_avail_models.index(st.session_state.pref_phone_model)
    new_p_model = st.selectbox("기종 선택", curr_avail_models, index=pm_idx, key="sb_widget_phone_model")

    if new_p_model != st.session_state.pref_phone_model:
        st.session_state.pref_phone_model = new_p_model
        if supabase_client and st.session_state.get("logged_in"):
            try: supabase_client.auth.update_user({"data": {"pref_phone_model": new_p_model}})
            except Exception: pass
        st.rerun()

    st.markdown("---")

    # 3) 저장된 내역 불러오기
    st.header("📁 저장된 내역 불러오기")
    db_history = db_fetch_user_history()
    if db_history:
        st.caption(f"현재 보관 수량: **{len(db_history)} / {MAX_SAVE_LIMIT} 개**")
        titles = [f"{h['title']} ({h['created_at'][:10]})" for h in db_history]
        selected_idx = st.selectbox("불러올 작업 선택", range(len(titles)), format_func=lambda x: titles[x])
        selected_row = db_history[selected_idx]
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            if st.button("📂 불러오기", use_container_width=True):
                loaded_color = selected_row.get("color_name", "")
                st.session_state.color_name = loaded_color
                st.session_state.color_name_input = loaded_color
                
                st.session_state.current_stage = selected_row["stage"]
                if selected_row.get("brand") in valid_brands:
                    st.session_state.pref_brand = selected_row["brand"]
                    
                st.session_state.ai_result_text = selected_row.get("ai_result", "")
                try: st.session_state.recipe_table_df = pd.read_json(io.StringIO(selected_row["recipe_json"]))
                except Exception: pass
                
                if "editor_active_recipe" in st.session_state: del st.session_state["editor_active_recipe"]
                st.toast(f"📂 '{selected_row['title']}' 내역을 성공적으로 불러왔습니다!")
                st.rerun()
        with col_s2:
            if st.button("🗑️ 삭제하기", use_container_width=True):
                db_delete_work(selected_row['id'])
                st.toast("🗑️ 데이터가 삭제되었습니다.")
                st.rerun()
    else:
        st.caption("보관함이 비어있습니다.")

    st.markdown("---")
    
    # 4) 초기화
    st.header("⚙️ 시스템 설정")
    if st.button("🔄 새로운 작업 시작 (Reset)", use_container_width=True):
        reset_workspace()
        st.toast("✨ 새로운 작업 화면으로 초기화되었습니다.")
        st.rerun()

# ----------------------------------------------------
# 6. 메인 화면 구성
# ----------------------------------------------------
current_brand = st.session_state.pref_brand
current_camera = f"{st.session_state.pref_phone_brand} {st.session_state.pref_phone_model}"

st.markdown(f"""<div class="noroo-header-box">
    <span class="noroo-brand-name">MULTI-BRAND AUTO COLOR SYSTEM</span>
    <h1 class="noroo-main-title">[{current_brand}] AI 스마트 조색 & 결함 진단</h1>
</div>""", unsafe_allow_html=True)

st.markdown("---")

tab_tuning, tab_defect = st.tabs([f"🎨 {current_brand} AI 미세 조색", "🔍 도장 결함 진단"])

with tab_tuning:
    current_stage = st.session_state.current_stage
    is_stage_1 = (current_stage == 1)
    stage_code = f"{current_stage}차"
    prev_stage_code = "1차" if current_stage == 2 else f"{current_stage-1}차"
    
    st.markdown(f'<div class="stage-badge">📍 현재 진행 단계: {current_brand} {stage_code} 조색 프로세스</div>', unsafe_allow_html=True)
    st.subheader("0. 차종 및 색상명/코드 입력")
    
    col_c1, col_c2 = st.columns([3.5, 1])
    with col_c1:
        input_color_val = st.text_input(
            "차종 및 목표 색상코드/색상명을 입력하세요",
            placeholder="예: 기아 ABT, 현대 SWP 등",
            key="color_name_input"
        )
        st.session_state.color_name = input_color_val

    with col_c2:
        st.write(""); st.write("")
        color_code_str = st.session_state.color_name.strip()
        auto_default_title = f"{datetime.now().strftime('%Y-%m-%d')}_{color_code_str}" if color_code_str else f"{datetime.now().strftime('%Y-%m-%d')}_색상미지정"
        if st.button("💾 클라우드 저장", type="primary", use_container_width=True):
            if not color_code_str: st.warning("⚠️ 차종 및 색상명을 입력한 후 저장해 주세요.")
            else: db_save_work(auto_default_title, current_brand); st.rerun()

    st.markdown("---")
    col_t1, col_t2 = st.columns(2)
    
    with col_t1:
        st.write("1. 목표 차체/판넬 사진 (Target)")
        st.markdown("""<div class="distance-guide-box"><b>📏 15cm 거리 촬영</b> <br>💡 <b>안내</b>: 실시간 촬영은 [📷 앱 내 직접 촬영]을, 스마트폰 사진첩의 기존 사진은 [📁 사진첩 (갤러리)]를 이용하세요.</div>""", unsafe_allow_html=True)
        if st.session_state.target_img_bytes is None:
            t_tab1, t_tab2 = st.tabs(["📷 앱 내 직접 촬영", "📁 사진첩 (갤러리)"])
            with t_tab1:
                cam = st.camera_input("목표 차체 촬영", key="cam_target")
                if cam: st.session_state.target_img_bytes = cam.getvalue(); st.rerun()
            with t_tab2:
                up = st.file_uploader("사진첩/갤러리에서 선택", type=["jpg", "png", "jpeg"], key="file_target")
                if up: st.session_state.target_img_bytes = up.getvalue(); st.rerun()
        else:
            st.image(load_and_resize(st.session_state.target_img_bytes), caption=f"🎯 목표 [{st.session_state.color_name}] - [{current_camera}]", use_container_width=True)
            if st.button("🔄 목표 사진 다시 찍기"): st.session_state.target_img_bytes = None; st.rerun()

    with col_t2:
        st.write(f"2. {stage_code} 도장 시편 사진 (Sample)")
        st.markdown("""<div class="distance-guide-box"><b>📏 15cm 거리 촬영</b> <br>💡 <b>안내</b>: 실시간 촬영은 [📷 앱 내 직접 촬영]을, 스마트폰 사진첩의 기존 사진은 [📁 사진첩 (갤러리)]를 이용하세요.</div>""", unsafe_allow_html=True)
        s_tab1, s_tab2 = st.tabs(["📷 앱 내 직접 촬영", "📁 사진첩 (갤러리)"])
        with s_tab1:
            cam_s = st.camera_input(f"{stage_code} 시편 촬영", key=f"cam_sample_{current_stage}")
            if cam_s: st.session_state.temp_sample_bytes = cam_s.getvalue()
        with s_tab2:
            up_s = st.file_uploader("사진첩/갤러리에서 선택", type=["jpg", "png", "jpeg"], key=f"file_sample_{current_stage}")
            if up_s: st.session_state.temp_sample_bytes = up_s.getvalue()
        if st.session_state.temp_sample_bytes:
            st.image(load_and_resize(st.session_state.temp_sample_bytes), caption=f"🧪 {stage_code} 시편 - [{current_camera}]", use_container_width=True)

    if not is_stage_1 and st.session_state.prev_sample_bytes and st.session_state.target_img_bytes and st.session_state.temp_sample_bytes:
        st.markdown("---")
        st.markdown(f"""<div class="comparison-card"><h4 style="margin-top:0; color:#003375;">📱 [{current_brand}] 초고화질 3분할 정밀 대조</h4></div>""", unsafe_allow_html=True)
        st.image(create_3way_split_view(st.session_state.prev_sample_bytes, st.session_state.target_img_bytes, st.session_state.temp_sample_bytes, crop_ratio=0.4), caption=f"◀️ {prev_stage_code} 시편 | 🎯 목표 차체 [{st.session_state.color_name}] | {stage_code} 신규 시편 ▶️", use_container_width=True)

    st.markdown("---")
    
    # ----------------------------------------------------
    # 3. 배합 레시피 작성 (★ 모바일 100% 한 화면 맞춤 표 ★)
    # ----------------------------------------------------
    st.subheader(f"3. {prev_stage_code if not is_stage_1 else '1차 기본'} 배합 레시피 ({current_brand})")
    
    if is_stage_1:
        st.caption("📷 **배합표 사진 인식**: 사진을 촬영하여 표에 수치를 자동 채우거나, 아래 표의 안료 코드 셀을 클릭하여 직접 선택/입력하세요.")
        cam_r = st.camera_input("배합표 카드 촬영 (선택)", key="cam_recipe")
        file_r = st.file_uploader("카드 사진 업로드 (선택)", type=["jpg", "png"], key="file_recipe")
        
        recipe_img_bytes = cam_r.getvalue() if cam_r else (file_r.getvalue() if file_r else None)
        if recipe_img_bytes:
            st.image(Image.open(io.BytesIO(recipe_img_bytes)), width=300)
            if st.button("🔍 카드 사진에서 안료 수치 읽어와 표에 반영"):
                with st.spinner("AI 분석 중..."):
                    df = extract_df_from_recipe_image(client, recipe_img_bytes, current_brand)
                    if df is not None and not df.empty:
                        st.session_state.recipe_table_df = df
                        st.success("표에 자동 채우기 완료!")
                        st.rerun()
                    else: st.warning("인식 실패. 아래 표에서 직접 선택해 주세요.")

    st.write(f"📋 **{current_brand} 확정 배합표 (표 안료 코드 셀을 클릭한 뒤 번호(예: 7, W110, A031, K100)를 입력하면 연관 안료가 정렬됩니다):**")
    
    current_brand_pigments = list(BRAND_CONFIGS[current_brand].get("pigments", []))
    existing_codes = st.session_state.recipe_table_df["안료 코드"].dropna().unique().tolist()
    for code in existing_codes:
        if code and str(code).strip() and str(code).strip() not in current_brand_pigments:
            current_brand_pigments.append(str(code).strip())

    current_brand_pigments = [p for p in current_brand_pigments if str(p).strip()]

    # ★ 모바일 화면에 맞춰 컬럼명을 간결하게 단축 및 가로 비율 자동 맞춤 ★
    st.session_state.recipe_table_df = st.data_editor(
        st.session_state.recipe_table_df,
        column_config={
            "안료 코드": st.column_config.SelectboxColumn(
                "안료 코드",
                help="셀 클릭 후 안료 번호(예: 7, W110, A031, K100)를 입력하세요",
                width="medium",
                options=current_brand_pigments,
                required=True
            ),
            "1차 배합 중량 (g)": st.column_config.NumberColumn(
                "중량 (g)",
                help="중량을 g 단위로 입력하세요",
                min_value=0.0,
                max_value=10000.0,
                step=0.1,
                width="small",
                format="%.2f g"
            )
        },
        use_container_width=True,
        num_rows="dynamic",
        key="editor_active_recipe"
    )

    st.markdown("---")

    # ----------------------------------------------------
    # AI 실행 버튼 (기본 100g 분석 기준)
    # ----------------------------------------------------
    if st.button(f"🚀 [{current_brand}] {stage_code} AI 미세 조색 분석 실행 (기본 100g 기준)", type="primary", use_container_width=True):
        if not st.session_state.target_img_bytes or not st.session_state.temp_sample_bytes:
            st.warning("⚠️ 목표 사진과 시편 사진을 모두 등록해 주세요.")
        elif is_stage_1 and st.session_state.recipe_table_df.empty:
            st.warning("⚠️ 배합표를 작성해 주세요.")
        else:
            with st.spinner("AI 실시간 색공간 분석 중..."):
                try:
                    img_t = load_and_resize(st.session_state.target_img_bytes)
                    img_c = load_and_resize(st.session_state.temp_sample_bytes)
                    rag = db_get_successful_recipes_rag(current_brand, st.session_state.color_name)
                    
                    prompt = f"""
                    [{current_brand}] 자동차 페인트 초정밀 조색 분석 지침.
                    - 차종/색상명: {st.session_state.color_name}
                    - 현 1차 배합표: \n{st.session_state.recipe_table_df.to_string(index=False)}
                    - 기준 분석 중량: 100g
                    - 촬영 기기 및 보정: {current_camera} ({CAMERA_PROFILES[st.session_state.pref_phone_brand][st.session_state.pref_phone_model]})
                    - 브랜드 특수 조색 수칙: {BRAND_CONFIGS[current_brand]['special_rules']}
                    {rag}
                    
                    [도료사 물리/화학 조색 핵심 수칙 강제 적용]
                    1. 노루 WATER-Q: Q-7000(플롭조절제) 10% 초과 시 Q-7800/7900 고은폐 백색 필수 대체. Q-3550 메탈릭 금지, Q-7350 솔리드 금지.
                    2. 시켄스 Optima/Autowave: W110 20% 초과 시 고농축 W120 전환. 저농도 Z1070 (Z160 1g=Z1070 16.67g), Y4050/Y4060 환산. SE8SA 크롬 초박막 도포. C070 Flop Control 배향 제어.
                    3. Glasurit 90Line: Abtöntabelle 정측면 보정 매트릭스 및 Multi-Effekt 펄 수칙. M1 Flop Control 입자 배향 제어. 93-E3/E10 50% 희석비 계산.
                    4. KCC Sumix WT: K100 표준백색 메탈릭 혼합 금지(입자감 상실). K101 저농도 백색 5% 이내 제한. K102 측면 조절용(정어둡/측밝). K807 스파클링 실버 탁함 주의.
                    5. 엑솔타 Hi-TEC 480: WT 385/387 컴포넌트, WT 386 Flop Control, 1-Visit (1.5 횟수도포) 공정 반영.
                    6. R-M Onyx HD: Chromatic Color Wheel 수칙 적용. HB090 Flop Control 적용.
                    7. PPG Envirobase: T403 Micro White 정측면 명도 반전 제어, T492 Adjuster (10%/20%/30%) 희석 수칙 적용.
                    
                    Delta E <= 0.5 판정 시 '[판정: 🎉 조색 완벽 합격 (Delta E <= 0.5)]' 명시.
                    아니면 '[판정: 🔺 미세 보정 필요]' 명시.
                    표 출력형태 (100g 기준): | 안료 코드 | {prev_stage_code} 중량 | {stage_code} 신규 중량 | 차이 | 처방 역할 |
                    """
                    res = client.models.generate_content(model="gemini-3.5-flash", contents=[img_t, img_c, prompt])
                    st.session_state.ai_result_text = res.text
                    
                    if "조색 완벽 합격" in res.text or "Delta E <= 0.5" in res.text: st.session_state.is_passed = True; st.session_state.show_next_btn = False
                    else: st.session_state.is_passed = False; st.session_state.show_next_btn = True
                    df = extract_recipe_df_from_ai_text(res.text, current_brand)
                    if df is not None and not df.empty: st.session_state.recipe_table_df = df
                except Exception as e: st.error(f"오류: {e}")

    # ----------------------------------------------------
    # 6-1. AI 결과 분석 및 목표 배합량 재계산 & 카드 이미지 다운로드
    # ----------------------------------------------------
    if st.session_state.ai_result_text:
        st.markdown("---")
        st.markdown(f"### 📊 AI 색공간 리포트 & 배합 비율 조율")
        st.markdown(st.session_state.ai_result_text)
        
        if st.session_state.is_passed:
            st.balloons()
            st.success("🎉 Delta E <= 0.5 이하로 조색이 완벽히 합격 처리되었습니다! 성공 족보로 자동 등록됩니다.")

        st.markdown("---")
        
        st.subheader("⚖️ 최종 작업 목표 배합량 재계산 & 카드 다운로드")
        
        active_df = st.session_state.recipe_table_df.copy()
        current_sum = active_df["1차 배합 중량 (g)"].sum() if not active_df.empty else 100.0
        if current_sum <= 0: current_sum = 100.0
        
        target_work_weight = st.number_input(
            "🎯 내가 현장에서 배합할 최종 목표 총 중량 (g)",
            min_value=10.0,
            max_value=10000.0,
            value=float(round(current_sum, 1)),
            step=10.0,
            key="user_target_work_weight"
        )
        
        scaled_df = active_df.copy()
        scale_factor = target_work_weight / current_sum
        scaled_df["1차 배합 중량 (g)"] = scaled_df["1차 배합 중량 (g)"] * scale_factor
        scaled_df["1차 배합 중량 (g)"] = scaled_df["1차 배합 중량 (g)"].round(2)
        
        st.write(f"📋 **[{target_work_weight:.1f}g 작업 기준] 최종 안료 계량표:**")
        st.dataframe(scaled_df, use_container_width=True)
        
        card_img_bytes = create_recipe_image_card(
            brand_name=current_brand,
            color_name=st.session_state.color_name,
            stage_code=stage_code,
            recipe_df=scaled_df,
            total_weight=target_work_weight,
            thinner_info=BRAND_CONFIGS[current_brand]["thinner_info"],
            special_rules=BRAND_CONFIGS[current_brand]["special_rules"]
        )
        
        download_filename = f"{datetime.now().strftime('%Y%m%d')}_{st.session_state.color_name if st.session_state.color_name else 'Color'}_배합표.png"
        
        col_down1, col_down2 = st.columns([1, 1])
        with col_down1:
            st.image(card_img_bytes, caption="📱 스마트폰 저장용 생성 이미지 카드 미리보기", use_container_width=True)
        with col_down2:
            st.write("📥 **스마트폰 갤러리에 카드 파일 저장**")
            st.caption("아래 버튼을 터치하면 최종 배합 수치, 색상명, 안료 코드가 정갈하게 기록된 배합표 이미지 카드를 핸드폰으로 즉시 다운로드할 수 있습니다.")
            st.download_button(
                label="📥 배합표 카드 이미지 다운로드 (갤러리 저장)",
                data=card_img_bytes,
                file_name=download_filename,
                mime="image/png",
                type="primary",
                use_container_width=True
            )

    if st.session_state.show_next_btn and not st.session_state.is_passed:
        st.markdown("---")
        st.button(f"➡️ {current_stage + 1}차 조색 단계로 진행하기", on_click=go_next_stage, type="primary", use_container_width=True)

# ----------------------------------------------------
# TAB 2: 도장 결함 진단 모듈
# ----------------------------------------------------
with tab_defect:
    st.subheader(f"🔍 [{current_brand}] 도장 결함 원인 분석 및 재작업 가이드")
    col1, col2 = st.columns(2)
    with col1:
        d_tab1, d_tab2 = st.tabs(["📷 카메라", "📁 사진첩 (갤러리)"])
        def_img = None
        with d_tab1:
            cam_d = st.camera_input("촬영", key="cam_def")
            if cam_d: def_img = cam_d.getvalue()
        with d_tab2:
            up_d = st.file_uploader("사진 선택", type=["jpg", "png"], key="file_def")
            if up_d: def_img = up_d.getvalue()
        if def_img: st.image(load_and_resize(def_img), use_container_width=True)
    with col2:
        def_ctx = st.text_area("현장 증상 요약", placeholder="예: 오렌지필 현상, 건조 60도")
    if st.button("🚨 진단 실행", type="primary", use_container_width=True):
        if def_img:
            with st.spinner("분석 중..."):
                res = client.models.generate_content(model="gemini-3.5-flash", contents=[load_and_resize(def_img), f"결함 진단. 브랜드:{current_brand}, 기기:{current_camera}, 증상:{def_ctx}"])
                st.success("진단 완료!"); st.markdown(res.text)
        else: st.warning("사진을 등록하세요.")