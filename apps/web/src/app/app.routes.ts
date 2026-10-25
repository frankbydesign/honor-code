import { Routes } from '@angular/router';
import { MeetingDetailComponent } from './meeting-detail/meeting-detail.component';
import { MeetingsComponent } from './meetings/meetings.component';
import { ReviewComponent } from './review/review.component';

export const routes: Routes = [
  { path: '', component: ReviewComponent, title: 'Review · Honor Code' },
  { path: 'meetings', component: MeetingsComponent, title: 'Meetings · Honor Code' },
  { path: 'meetings/:id', component: MeetingDetailComponent, title: 'Meeting · Honor Code' },
  { path: '**', redirectTo: '' },
];
