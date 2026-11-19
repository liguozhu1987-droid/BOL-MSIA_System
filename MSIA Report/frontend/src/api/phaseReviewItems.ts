import { http } from './client';

// 单档评分标准 (与后端对齐)
export interface ScoreOption {
  score: number;
  desc: string;
}

// 阶段评审检查项 (与后端 PhaseReviewItem 对齐, 字段为 PascalCase)
export interface PhaseReviewItem {
  Id: number;
  PhaseCode: string;
  Seq: number;
  ItemType?: string | null;
  ItemName: string;
  Request?: string | null;
  // 100% 评分档的描述要求 (从 CheckItem.ScoreOptions 提取)
  Maturity100Desc?: string | null;
  // 本检查项专属 7 档评分标准 [{score, desc}, ...]
  ScoreOptions?: ScoreOption[] | null;
  DefaultResultText?: string | null;
  SortOrder: number;
  IsDeleted?: boolean;
  CreatedAt?: string | null;
  UpdatedAt?: string | null;
}

// 按阶段代码获取评审检查项清单 (来自 Report MSIA1~5 sheet)
export function getPhaseReviewItems(phaseCode: string): Promise<PhaseReviewItem[]> {
  return http.get<PhaseReviewItem[]>('/phase-review-items', {
    params: { phase_code: phaseCode },
  });
}
