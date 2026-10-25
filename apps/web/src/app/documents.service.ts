import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../environments/environment';
import { Commitment, DocumentDetail, DocumentSummary, ExtractionRun } from './api/models';

@Injectable({ providedIn: 'root' })
export class DocumentsService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/documents`;
  private readonly opts = { withCredentials: true };

  list(): Observable<DocumentSummary[]> {
    return this.http.get<DocumentSummary[]>(this.base, this.opts);
  }

  get(id: string): Observable<DocumentDetail> {
    return this.http.get<DocumentDetail>(`${this.base}/${id}`, this.opts);
  }

  extract(id: string): Observable<{ run: ExtractionRun; commitments: Commitment[] }> {
    return this.http.post<{ run: ExtractionRun; commitments: Commitment[] }>(`${this.base}/${id}/extract`, null, this.opts);
  }

  remove(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}`, this.opts);
  }
}
